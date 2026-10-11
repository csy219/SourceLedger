# 这是**全链路可观测性层的统一能力事件模型**，属于「内部追踪事件 → 外部标准事件」的适配转换层。

# 简单说：你之前整条 RAG 链路里各个阶段生成的 `TraceEvent` 是**内部流程用的轻量追踪事件**；而 `CapabilityEvent` 是**对外输出的标准化事件格式**，适合输出到监控、审计、日志、告警系统，两者可以双向无损转换。

# 它的核心价值是：内部追踪追求灵活高效，对外事件追求规范强校验，两者解耦又互通
# 事件模型	定位	使用场景	校验强度
# TraceEvent	内部链路追踪事件	RAG 各阶段内部串链路、排障	弱，灵活优先
# CapabilityEvent	统一标准能力事件	对外输出监控、审计、事件总线	强，规范优先
# 两者可以双向转换：

# - 内部 trace 可以批量导出成标准能力事件
# - 外部事件也可以转回内部格式处理
"""Unified capability event model for SourceLedger."""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from typing import Any
from uuid import uuid4

from runtime.rag_contracts import (
    ContractModel,
    TraceEvent,
    TraceStatus,
    utc_now,
)
# 二、`CapabilityEvent` 标准事件类
# 字段	作用	说明
# event_id	全局唯一事件 ID	默认自动生成 evt- 前缀 + UUID，全局唯一，适合分布式追踪
# run_id	请求链路 ID	关联整条用户请求，和内部链路的 run_id 完全对齐
# timestamp	事件发生时间	默认 UTC 标准时间，全局时区统一
# stage	所属阶段	如 retrieval / context / generation
# operation	操作名称	如 vector_search / rrf_fusion
# status	事件状态	复用 TraceStatus 枚举：STARTED / SUCCEEDED / FAILED / FALLBACK_USED
# attempt	第几次尝试	重试场景下标记第几次，默认 1
# action	具体动作	更细粒度的动作描述
# duration_ms	耗时（毫秒）	操作执行时长
# metadata	扩展元数据	键值对，承载任意业务指标
@dataclass
class CapabilityEvent(ContractModel):
    event_id: str = field(default_factory=lambda: f"evt-{uuid4().hex}")
    run_id: str = ""
    timestamp: str = field(default_factory=utc_now)
    stage: str = ""
    operation: str = ""
    status: TraceStatus = TraceStatus.STARTED
    attempt: int = 1
    action: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # `__post_init__` 强校验
    #     这是对外事件的**质量闸门**：

    # - 所有核心字段非空校验
    # - 业务规则校验（尝试次数≥1、时长非负）
    # - 保证输出到外部监控 / 审计系统的事件都是合法的，不会出现脏数据

    # > 
    # > 这也是和内部 `TraceEvent` 最大的区别：内部追踪为了灵活可以宽松，对外输出必须严格校验。
    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not self.timestamp.strip():
            raise ValueError("timestamp cannot be empty")
        if not self.stage.strip():
            raise ValueError("stage cannot be empty")
        if not self.operation.strip():
            raise ValueError("operation cannot be empty")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")

    # 三、双向转换方法
    # 1. `from_trace_event` —— 内部事件转标准事件
    @classmethod
    def from_trace_event(cls, event: TraceEvent) -> "CapabilityEvent":
        return cls(
            event_id=event.event_id,
            run_id=event.run_id,
            timestamp=event.started_at or utc_now(),
            stage=event.stage,
            operation=event.operation,
            status=event.status,
            attempt=event.attempt,
            action=event.action,
            duration_ms=event.duration_ms,
            metadata=dict(event.metadata),
        )

    # 2. `to_trace_event` —— 标准事件转回内部事件
    # - 实例方法，把标准事件转回内部追踪事件格式
    # - 价值：双向兼容，外部进来的事件也可以在内部链路里复用处理逻辑
    def to_trace_event(self) -> TraceEvent:
        return TraceEvent(
            event_id=self.event_id,
            run_id=self.run_id,
            stage=self.stage,
            operation=self.operation,
            status=self.status,
            attempt=self.attempt,
            action=self.action,
            started_at=self.timestamp,
            duration_ms=self.duration_ms,
            metadata=dict(self.metadata),
        )

# 四、批量转换工具
# - 输入一整条链路的 trace 元组
# - 批量转换成标准能力事件元组
# - 这是最常用的入口：整条 RAG 链路跑完，调用这个函数就能把内部 trace 一次性导出成标准事件，推送给监控、审计系统。
def events_from_trace(trace: tuple[TraceEvent, ...]) -> tuple[CapabilityEvent, ...]:
    return tuple(CapabilityEvent.from_trace_event(event) for event in trace)

## 五、核心设计价值

# 1. **内外解耦**
# 内部追踪事件和对外标准事件分开定义，内部改流程不影响外部系统，外部改格式也不破坏内部链路。
# 2. **强校验边界**
# 对外输出的事件经过 `__post_init__` 全量校验，保证监控、审计系统收到的数据都是合法的。
# 3. **双向无损转换**
# 可以互相转，现有内部链路的所有历史 trace 都可以直接导出成标准格式，不用重构历史代码。
# 4. **全局统一**
# 统一的事件 ID 规则、时间标准、字段定义，适合多系统、分布式场景下的全链路追踪。

# ---

# ## 六、在架构中的位置

# ```
# RAG 内部各阶段
#     生成 TraceEvent
#         ↓
#   汇总到 Run.trace
#         ↓
# events_from_trace() 批量转换
#         ↓
#   CapabilityEvent 标准事件
#         ↓
# 输出到：监控 / 审计 / 告警 / 事件总线
# ```

# 它是整条 RAG 系统可观测性的「出口适配器」，把内部的流程追踪数据，转换成对外标准的事件数据。