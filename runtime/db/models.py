from datetime import datetime,timezone
from typing import Any

# 从 SQLAlchemy 导入**数据库字段类型**和**约束 / 索引工具**：
# - `Integer` / `String` / `Text` / `DateTime` / `JSON`：对应数据库里的列类型
# - `ForeignKey`：外键，用来关联两张表
# - `UniqueConstraint`：唯一约束，保证某几个字段组合不重复
# - `Index`：索引，加速查询速度
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

# ORM 核心工具：
# - `DeclarativeBase`：ORM 基类，所有表模型都要继承它
# - `Mapped[类型]`：SQLAlchemy 2.0 的类型注解写法，标明这个属性对应数据库一列，同时指定 Python 侧的类型
# - `mapped_column()`：真正定义列的规则（主键、长度、是否可为空、默认值等）
from sqlalchemy.orm import(
    DeclarativeBase,
    Mapped,
    mapped_column,
)

def utc_now()->datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class RunRow(Base):
    __tablename__="runs"

    run_id: Mapped[str] = mapped_column(
        String(64),
        # 主键 primary_key=True
        primary_key=True,
    )
    thread_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    goal: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    current_node: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="start",
    )
    step_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_steps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
    )
    created_at:Mapped[datetime]=mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # - 表级**组合索引**：按 `thread_id + status` 联合查询时速度更快。
    # - 场景：恢复时快速查「某个线程下正在运行的任务」。

    __table_args__=(
        Index(
            "ix_runs_thread_status",
            "thread_id",
            "status",
        ),
    )

class CheckpointRow(Base):
    __tablename__ = "checkpoints"

    checkpoint_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    node: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    state_snapshot: Mapped[dict[str, Any]] = (
        mapped_column(
            JSON,
            nullable=False,
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    #     每次关键节点都新增一条快照，而不是覆盖旧状态。
    # UniqueConstraint(
    #     "run_id",
    #     "version",
    # )
    # 保证同一个任务不会出现两个相同版本号。

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "version",
            name="uq_checkpoints_run_version",
        ),
        Index(
            "ix_checkpoints_run_created",
            "run_id",
            "created_at",
        ),
    )

class ToolCallRow(Base):
    __tablename__ = "tool_calls"

    tool_call_pk: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id"),
        nullable=False,
        index=True,
    )
    tool_call_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    arguments: Mapped[dict[str, Any]] = (
        mapped_column(
            JSON,
            nullable=False,
            default=dict,
        )
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )
    result: Mapped[Any | None] = mapped_column(
        JSON,
        nullable=True,
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    started_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )
    finished_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "tool_call_id",
            name="uq_tool_calls_run_call",
        ),
        Index(
            "ix_tool_calls_run_status",
            "run_id",
            "status",
        ),
    )


class IdempotencyKeyRow(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    result: Mapped[Any | None] = mapped_column(
        JSON,
        nullable=True,
    )
    error: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    