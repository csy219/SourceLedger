# 这段代码是一套**完整的工具调用记录持久化仓储层（ToolCallRepository）**，
# 是 Agent / 工作流系统里的核心组件，用来记录每一次工具调用的全生命周期信息
# （参数、状态、重试次数、结果、错误、耗时），并且做了幂等性、并发安全、状态流转封装

# 业务层 → ToolCallSummary（业务DTO） → ToolCallRepository（仓储） → ToolCallRow（ORM模型） → 数据库

from dataclasses import dataclass
from datetime import datetime,timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from runtime.S15_state_reference import (
    ToolCallRecord,
    ToolCallStatus,
)

from runtime.db.models import ToolCallRow

# **设计意图**：
# - 统一使用 UTC 时区存储时间，彻底避免多部署节点时区不一致导致的时序错乱。
# - `parse_datetime` / `format_datetime` 做类型转换：数据库存 `datetime` 对象，业务层传 ISO 格式字符串，两层互不感知。
def utc_now()->datetime:
    return datetime.now(timezone.utc)

def parse_datetime(value:str)->datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)

def format_datetime(value:datetime | None)->str:
    if not value :
        return ""
    return value.isoformat()

# 2. ToolCallSummary：业务层 DTO
@dataclass(frozen=True)
class ToolCallSummary:
    tool_call_id: str
    run_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: ToolCallStatus
    attempt: int
    max_attempts: int
    result: Any
    error: str
    started_at: str
    finished_at: str


def row_to_summary(
    row: ToolCallRow,
) -> ToolCallSummary:
    return ToolCallSummary(
        tool_call_id=row.tool_call_id,
        run_id=row.run_id,
        tool_name=row.tool_name,
        arguments=row.arguments,
        status=ToolCallStatus(row.status),
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        result=row.result,
        error=row.error,
        started_at=format_datetime(
            row.started_at
        ),
        finished_at=format_datetime(
            row.finished_at
        ),
    )

class ToolCallRepository:
    def __init__(self,session_factory:Any)->None:
        self.session_factory=session_factory

    # 1. `create_or_get`：幂等创建（最核心的设计
    # 这是**经典的「先查后插 + 异常兜底」幂等实现**，专门解决并发重复创建问题。
    #### 执行逻辑
    # 1. **先查**：用 `run_id + tool_call_id` 联合唯一键查询，存在就直接返回旧数据，标记 `False`（非新建）。
    # 2. **后插**：不存在就插入新记录，尝试提交。
    # 3. **异常兜底**：如果抛出 `IntegrityError`（唯一键冲突），说明高并发下另一个请求已经抢先插入了。此时回滚事务，再查一次，返回已存在的记录。
    # 4. 返回值 `tuple[结果, 是否新建]`：业务层可以根据第二个布尔值判断是不是第一次创建。
    # #### 为什么要这么设计？
    # 工具调用场景很容易出现重复触发：网络重试、任务重试、并发调度。如果直接 insert，会出现重复记录；如果只查不做异常兜底，高并发下还是会冲突报错。这套实现保证：

    # > 同一次工具调用（同一个 run 下同一个 tool_call_id），无论调用多少次 create_or_get，永远只会有一条记录，不会报错，也不会重复。
    def create_or_get(
        self,
        run_id:str,
        record:ToolCallRecord,
    )->tuple[ToolCallSummary,bool]:
        with self.session_factory() as session:
            # 第一步：先查是否已存在
            existing=session.scalar(
                select(ToolCallRow).where(
                    ToolCallRow.run_id==run_id,
                    ToolCallRow.tool_call_id==record.tool_call_id
                )
            )
            if existing is not None:
                return row_to_summary(existing),False
            
            # 第二步：不存在则构造新记录插入
            row = ToolCallRow(
                run_id=run_id,
                tool_call_id=record.tool_call_id,
                tool_name=record.tool_name,
                arguments=record.arguments,
                status=record.status.value,
                attempt=record.attempt,
                max_attempts=record.max_attempts,
                result=record.result,
                error=record.error,
                started_at=parse_datetime(
                    record.started_at
                ),
                finished_at=parse_datetime(
                    record.finished_at
                ),
            )

            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing=session.scalar(
                    select(ToolCallRow).where(
                        ToolCallRow.run_id==run_id,
                        ToolCallRow.tool_call_id==record.tool_call_id,
                    )
                )
                if existing is None:
                    raise
                return (row_to_summary(existing),False)

            session.refresh(row)
            return row_to_summary(row),True

    def get(
        self,
        run_id: str,
        tool_call_id: str,
    ) -> ToolCallSummary | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ToolCallRow).where(
                    ToolCallRow.run_id == run_id,
                    ToolCallRow.tool_call_id
                    == tool_call_id,
                )
            )
            if row is None:
                return None
            return row_to_summary(row)

    # 2. `mark_running`：标记为运行中
    #     对应工具**开始执行 / 重试执行**的动作：
    # - 状态置为 `RUNNING`
    # - 重试次数 `attempt` 自增 1（第一次执行也是 1，重试依次累加）
    # - 刷新开始时间
    # - 清空上一次的错误信息
    # > 完美支持重试机制：每次重试调用一次 mark_running，自动计数、重置状态
    def mark_running(self,run_id,tool_call_id)->ToolCallSummary | None:
        with self.session_factory() as session:
            row=session.scalar(
                select(ToolCallRow).where(
                    ToolCallRow.run_id==run_id,
                    ToolCallRow.tool_call_id==tool_call_id,
                )
            )
            if row is None:
                return None

            row.status=ToolCallStatus.RUNNING.value
            row.attempt+=1
            row.started_at=utc_now()
            row.error=""

            session.commit()
            session.refresh(row)
            return row_to_summary(row)

    # 3. `mark_succeeded`：标记执行成功
    def mark_succeeded(
        self,
        run_id: str,
        tool_call_id: str,
        result: Any,
    ) -> ToolCallSummary | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ToolCallRow).where(
                    ToolCallRow.run_id == run_id,
                    ToolCallRow.tool_call_id
                    == tool_call_id,
                )
            )
            if row is None:
                return None

            row.status = (
                ToolCallStatus.SUCCEEDED.value
            )
            row.result = result
            row.finished_at = utc_now()

            session.commit()
            session.refresh(row)
            return row_to_summary(row)
        
    # 4. `mark_failed`：标记执行失败
    # - 支持传入不同的失败状态（比如 `FAILED` 最终失败、`RETRYING` 待重试）
    # - 写入错误信息，方便排查问题
    # - 设置结束时间，可用于统计耗时
    def mark_failed(
        self,
        run_id: str,
        tool_call_id: str,
        status: ToolCallStatus,
        error: str,
    ) -> ToolCallSummary | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ToolCallRow).where(
                    ToolCallRow.run_id == run_id,
                    ToolCallRow.tool_call_id
                    == tool_call_id,
                )
            )
            if row is None:
                return None

            row.status = status.value
            row.error = error
            row.finished_at = utc_now()

            session.commit()
            session.refresh(row)
            return row_to_summary(row)

    # 5. `list_by_run`：按任务查询所有工具调用
    # - 按自增主键 `tool_call_pk` 升序排序，也就是按工具调用的先后顺序返回。
    # - 用于查看一次任务总共调用了哪些工具、执行顺序和结果，是链路追溯的基础。
    def list_by_run(
        self,
        run_id: str,
    ) -> list[ToolCallSummary]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ToolCallRow)
                .where(
                    ToolCallRow.run_id == run_id
                )
                .order_by(
                    ToolCallRow.tool_call_pk.asc()
                )
            ).all()

            return [
                row_to_summary(row)
                for row in rows
            ]