# 这段代码是**生产级 Agent / 工作流系统的核心组件：
# 数据库版检查点管理器（DatabaseCheckpointer）**，对应 LangGraph 里的 Checkpointer 能力，
# 核心作用是把运行中的完整状态快照持久化到数据库，实现**断点续跑、状态回溯、历史版本重放**。
# 它和你之前看到的 `RunRepository`、状态序列化工具是配套体系，共同构成完整的任务持久化方案。



### 1. 核心职责

# - **保存快照**：每执行完一个工作流节点，就把完整的 `RunState` 序列化为 JSON 存入数据库，生成新版本
# - **恢复状态**：任务中断 / 重启时，从数据库加载最新快照，还原内存状态，从断点继续执行
# - **版本管理**：支持查看所有历史版本、加载指定版本，实现状态回滚与审计
from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Any

from sqlalchemy import func,select

from runtime.S15_state_reference import RunState
from runtime.db.models import (
    CheckpointRow,
    RunRow,
)

from runtime.db.state_codec import (
    state_from_dict,
    state_to_dict,
)

# 1. 时间工具与摘要 DTO
def utc_now()->datetime:
    return datetime.now(timezone.utc)

@dataclass(frozen=True)
class CheckpointSummary:
    checkpoint_id:int
    run_id:str
    version:int
    node:str
    created_at:datetime


# 三、核心方法逐行解析
class DatabaseCheckpointer:
    def __init__(
            self,
            session_factory:Any
    )->None:
        self.session_factory=session_factory

    # 1. `save`：保存状态快照（最核心，并发安全设计）
    
    def save(
            self,
            state:RunState,
            node:str,
    )->CheckpointSummary:
        with self.session_factory() as session:
            # ① 锁定任务主记录（悲观行级锁）
            run_row = session.scalar(
                select(RunRow)
                .where(
                    RunRow.run_id
                    == state.run_id
                )
                .with_for_update()
            )

            if run_row is None:
                raise RuntimeError(
                    "保存 Checkpoint 前必须先创建 Run: "
                    f"{state.run_id}"
                )
            # ② 查询当前最大版本号，计算下一个版本
            latest_version=session.scalar(
                select(func.max(CheckpointRow.version))
                .where(CheckpointRow.run_id==state.run_id)
            )
            next_version=int(latest_version)+1 if latest_version else 1
            # ③ 构造快照记录：完整状态序列化为字典（对应数据库 JSON 字段）
            row = CheckpointRow(
                run_id=state.run_id,
                version=next_version,
                node=node,
                state_snapshot=state_to_dict(state),
            )
            session.add(row)

            # ④ 同步更新任务主表的核心状态字段（冗余设计换查询性能）
            run_row.status = state.status.value
            run_row.current_node = state.current_node
            run_row.step_count = state.step_count
            run_row.max_steps = state.max_steps
            run_row.updated_at = utc_now()

            session.commit()
            session.refresh(row)
            return CheckpointSummary(
                checkpoint_id=row.checkpoint_id,
                run_id=row.run_id,
                version=row.version,
                node=row.node,
                created_at=row.created_at,
            )
    # 2. `load_latest`：加载最新快照
    # - 按版本号倒序取第一条，就是最新的状态快照
    # - 反序列化为内存对象 `RunState`，直接可以交给工作流引擎继续执行
    # - **典型场景**：服务重启、任务中断恢复，从断点继续跑
    def load_latest(self, run_id: str) -> RunState | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(CheckpointRow)
                .where(CheckpointRow.run_id == run_id)
                .order_by(CheckpointRow.version.desc())
                .limit(1)
            )
            if row is None:
                return None
            return state_from_dict(row.state_snapshot)
    # 3. `load_version`：加载指定历史版本
    # - 按精确版本号加载历史状态
    # - **典型场景**：问题排查、状态回滚、工作流重放、A/B 对比
    def load_version(self,run_id:str,version:int)->RunState | None:
        with self.session_factory() as session:
            row=session.scalar(
                select(CheckpointRow)
                .where(
                    CheckpointRow.run_id==run_id,
                    CheckpointRow.version==version
                )
            )
            if row is None:
                return None
            return state_from_dict(row.state_snapshot)

    # 4. `list_versions`：列出所有版本号
    # - 返回该任务所有历史版本号的有序列表
    # - **典型场景**：前端版本选择器、审计追溯、批量清理旧版本
    def list_versions(
        self,
        run_id: str,
    ) -> list[int]:
        with self.session_factory() as session:
            versions = session.scalars(
                select(CheckpointRow.version)
                .where(
                    CheckpointRow.run_id == run_id
                )
                .order_by(
                    CheckpointRow.version.asc()
                )
            ).all()

            return [
                int(version)
                for version in versions
            ]

## 四、整体设计思想与价值

### 1. 冷热分离，兼顾性能与完整性

# - **热数据（RunRow）**：核心状态字段，体积小、查询频繁，用于列表、筛选、监控
# - **冷数据（CheckpointRow）**：完整状态快照，体积大、查询少，用于恢复、回溯
# 两者同步更新，既保证查询性能，又不丢失完整状态。

# ### 2. 全量快照，简单可靠

# 每次保存都存完整的状态副本，而不是存增量 diff。好处是：

# - 恢复逻辑极其简单，直接加载最新版本即可
# - 没有增量合并的复杂度，不会出现累计误差
# - 任意版本都可以独立使用，不依赖历史版本

# ### 3. 并发安全，生产可用

# 通过 `with_for_update` 悲观锁保证同任务串行保存，避免并发场景下的版本冲突、数据覆盖，是工业级实现的标志。

# ### 4. 职责单一，解耦上层

# Checkpointer 只负责「存状态、取状态」，完全不关心状态内部结构和业务逻辑，序列化全部委托给 `state_codec`，上层工作流引擎也不用感知数据库细节。

# ---

# ## 五、和之前仓储的关系与完整链路

# ### 分工区别

# - `RunStateRepository`：任务生命周期管理（创建、更新状态、查询列表），面向结构化查询
# - `DatabaseCheckpointer`：运行时状态快照管理（保存 / 恢复完整状态），面向断点续跑和回溯
# - 两者都会更新 `RunRow`，但角度不同：前者是业务操作，后者是运行时同步

# ### 完整运行链路

# ```
# 任务启动 → RunRepository 创建任务
#     ↓
# 每执行完一个节点 → Checkpointer.save(state, 当前节点名)
#     ↓ （服务重启 / 进程中断）
# 任务恢复 → Checkpointer.load_latest(run_id) → 还原内存状态
#     ↓
# 从快照记录的 node 节点继续执行