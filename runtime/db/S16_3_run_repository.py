# 16-3 要解决什么
# 执行图不应该直接拼 SQL，而应该通过 Repository：
# RuntimeGraph
#     |
#     v
# RunStateRepository
#     |
#     v
# runs 表

# Repository 的职责：
# 创建 Run 记录
# 读取 Run 摘要
# 更新当前节点
# 更新任务状态
# 按 thread_id 查询该会话的任务

# 这段是 **S16-3：RunStateRepository 实现**，采用经典的**仓库模式（Repository Pattern）**，专门封装 `runs` 任务主表的所有数据库操作，把业务层和持久化层彻底隔离开。上层的 Checkpointer、状态机只需要和内存里的 `RunState` 打交道，不用直接碰 ORM 模型和 SQL。

### 一、先理清三层对象的对应关系

# 在继续看代码前，先搞懂三类对象的分工，后面就不会乱：

# 表格

# | 对象 | 所在层 | 作用 |
# | --- | --- | --- |
# | `RunState` | 业务 / 内存层 | S15 定义的内存运行状态，状态机直接操作它 |
# | `RunRow` | 持久化层 | S16-1 定义的 ORM 模型，和数据库 `runs` 表一一对应 |
# | `RunSummary` | 传输层 | 只读数据类，在两层之间传数据，不暴露数据库实体 |

# 核心原则：**数据库实体 `RunRow` 绝对不流出仓库层**，上层拿到的永远是 `RunSummary` 这种纯数据对象，避免 Session 过期、懒加载异常等 ORM 坑。

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from runtime.S15_state_reference import (
    RunState,
    RunStatus,
)
from runtime.db.models import RunRow

# 二、数据传输对象 + 转换函数
@dataclass(frozen=True)
class RunSummary:
    run_id: str
    thread_id: str
    goal: str
    status: RunStatus
    current_node: str
    step_count: int
    max_steps: int
    created_at: datetime
    updated_at: datetime

def row_to_summary(
    row: RunRow,
) -> RunSummary:
    return RunSummary(
        run_id=row.run_id,
        thread_id=row.thread_id,
        goal=row.goal,
        status=RunStatus(row.status),
        current_node=row.current_node,
        step_count=row.step_count,
        max_steps=row.max_steps,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

# 三、RunStateRepository 核心类
class RunStateRepository:

    # - 构造时注入**会话工厂**，不直接持有 Session。
    # - 每个方法内部自己打开 Session、自己管理事务、用完就关，线程安全，连接自动回收到连接池。
    # - 这是标准的仓库实现：一个仓库实例全局复用，每次操作独立拿连接。
    def __init__(self,session_factory:Any)->None:
        self.session_factory=session_factory

    # 1. create：创建任务记录
    #     **执行流程：**
    # 1. 开会话 → 2. 主键查询判重 → 3. 已存在抛业务异常 → 4. 内存状态转数据库行 → 5. 插入提交 → 6. 刷新获取数据库自动生成的时间字段 → 7. 转成摘要返回。
    # **设计细节：**
    # - 提前判重：虽然主键本身会报错，但提前检查可以抛出更友好的业务异常，而不是数据库底层的 `IntegrityError`。
    # - `session.refresh(row)`：提交后刷新对象，拿到 `created_at`、`updated_at` 这些数据库默认生成的值，保证返回的是完整数据。
    # - 入参是内存里的 `RunState`，出参是 `RunSummary`，全程不暴露 `RunRow`。
    def create(self,state:RunState)->RunSummary:
        with self.session_factory() as session:
            existing=session.get(RunRow,state.run_id)
            if existing is not None:
                raise ValueError(f"Run已存在: {state.run_id}")
            row=RunRow(
                run_id=state.run_id,
                thread_id=state.thread_id,
                goal=state.goal,
                status=state.status.value,
                current_node=state.current_node,
                step_count=state.step_count,
                max_steps=state.max_steps,
            )

            session.add(row)
            session.commit()
            session.refresh(row)
            return row_to_summary(row)
    # 2. get_summary：按 ID 查询任务摘要
    # - 最基础的主键查询，**恢复流程的核心入口**：重启时先调用它，判断任务是否存在、当前是什么状态。
    # - 查不到返回 `None`，而不是抛异常，上层可以很方便地做判空处理。
    def get_summary(self,run_id:str)->RunSummary | None:
        with self.session_factory() as session:
            row=session.get(RunRow,run_id)
            if row is None:
                return None
            return row_to_summary(row)


    # 3. update_runtime_position：更新运行进度
    # - **运行过程中最高频调用的方法**：每走完一个节点，就更新一次任务的当前状态、节点名、步数。
    # - 只更新**运行时会变的 3 个字段**，不做全量覆盖，避免误改 `goal`、`thread_id` 这类固定信息，性能也更好。
    # - 任务不存在返回 `None`，上层可以判断任务是否被删除了。
    def update_runtime_position(
            self,
            run_id:str,
            status:RunStatus,
            current_node:str,
            step_count:int,
    )->RunSummary | None:
        with self.session_factory() as session:
            row=session.get(RunRow,run_id)
            if row is None:
                return None

            row.status=status.value
            row.current_node=current_node
            row.step_count=step_count
            session.commit()
            session.refresh(row)
            return row_to_summary(row)

    # 4. list_by_thread：按线程列历史任务
    # - 按 `thread_id` 查询该线程下的所有任务，按创建时间倒序（最新的在前）。
    # - 典型的列表查询场景：比如同一个用户 / 会话查看自己的历史任务列表。
    # - 用 SQLAlchemy 2.0 的 `select()` 语法构造查询，`scalars().all()` 直接拿到行对象列表，批量转换。
    def list_by_thread(self,thread_id:str)->list[RunSummary]:
        with self.session_factory() as session:
            rows=session.scalars(
                select(RunRow)
                .where(RunRow.thread_id==thread_id)
                .order_by(RunRow.created_at.desc())
            ).all()
            return [row_to_summary(row) for row in rows]