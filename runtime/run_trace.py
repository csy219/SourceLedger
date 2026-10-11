# 这是 **C02 链路追踪存储层**，属于全链路可观测体系的「事件聚合与存储基础设施」。
# 它把前面定义的单个 `CapabilityEvent` 按 `run_id`（请求 ID）聚合成完整的请求追踪链路，提供标准化的存储、
# 查询、管理能力，同时支持内存实现、数据库持久化、降级兜底、并发安全、容量防护等生产级特性。
# - `CapabilityEvent` = 单条事件
# - `RunTrace` = 一条请求的完整事件链路
# - `TraceStore` = 事件存储抽象
# - `TraceRecorder` = 上层业务用的事件记录入口
"""Run-scoped capability event aggregation and storage."""

from __future__ import annotations

import threading
from dataclasses import (
    dataclass,
    field,
)
from typing import Protocol

from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import (
    ContractModel,
    utc_now,
)

# 异常类	触发场景	父类
# TraceNotFoundError	查询的 run_id 不存在	KeyError
# TraceCapacityError	单条请求的事件数超过上限，防止内存泄漏	RuntimeError
# TraceDuplicateEventError	同一个 event_id 重复追加，保证事件幂等	RuntimeError
class TraceNotFoundError(KeyError):
    """Raised when a run trace does not exist."""
class TraceCapacityError(RuntimeError):
    """Raised when a run exceeds the event limit."""
class TraceDuplicateEventError(
    RuntimeError
):
    """Raised when an event_id is appended twice."""


# 二、`RunTrace` —— 单请求链路聚合对象
### 核心字段

# - `run_id`：请求唯一 ID，整条链路的主键
# - `events`：该请求的所有标准能力事件，按时间有序
# - `created_at`：链路创建时间（第一个事件的时间）
# - `updated_at`：链路最后更新时间（最后一个事件的时间）
@dataclass
class RunTrace(ContractModel):
    run_id: str
    events: tuple[CapabilityEvent, ...] = ()
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError(
                "run_id cannot be empty"
            )

        if any(
            event.run_id != self.run_id
            for event in self.events
        ):
            raise ValueError(
                "all events must match run_id"
            )

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def last_event(
        self,
    ) -> CapabilityEvent | None:
        if not self.events:
            return None

        return self.events[-1]


## 三、存储协议抽象（Protocol）
# 用 Python 的 `Protocol` 定义接口契约，**面向接口编程**，上层业务不依赖具体实现，可以无缝替换内存实现、数据库实现、Redis 实现等。

# 1. `TraceStore` —— 运行时存储接口
# 面向运行时场景的存储契约，是上层直接使用的接口：
# - `append_event(event)`：追加单个事件
# - `get_run(run_id)`：查询单条完整链路
# - `list_runs()`：列出所有 run_id
# - `clear()`：清空所有数据
class TraceStore(Protocol):
    def append_event(
        self,
        event: CapabilityEvent,
    ) -> None:
        ...

    def get_run(
        self,
        run_id: str,
    ) -> RunTrace:
        ...

    def list_runs(
        self,
    ) -> tuple[str, ...]:
        ...

    def clear(self) -> None:
        ...

### 2. `TraceRepository` —— 持久化仓库接口
# 面向数据库 / 持久化层的契约，供数据库适配器实现：
# - `append_event(event)`：持久化写入事件
# - `get_events(run_id)`：从持久层查询某条的所有事件
# - `list_run_ids()`：列出所有持久化的 run_id
# - `clear()`：清空持久化数据
class TraceRepository(Protocol):
    """Persistence interface implemented by a DB adapter."""

    def append_event(
        self,
        event: CapabilityEvent,
    ) -> None:
        ...

    def get_events(
        self,
        run_id: str,
    ) -> list[CapabilityEvent]:
        ...

    def list_run_ids(
        self,
    ) -> list[str]:
        ...

    def clear(self) -> None:
        ...
# 为什么要分两个协议？
# **职责分离**：

# - `TraceStore` 是运行时语义，关注「按 run 聚合、排序、校验、容量」
# - `TraceRepository` 是持久化语义，关注「读写数据库、批量查询」
# 两层可以独立演进、独立替换。


# 四、工具函数：`_sort_events`
# 事件排序工具，保证返回的链路是**按时间升序**的。
# - 主排序：按事件时间戳
# - 次排序：按原始插入顺序（稳定排序）
# - 输出：不可变元组

# > 设计价值：内存里追加是按顺序的，但数据库查询、并发写入可能导致乱序，输出前统一排序，保证链路时间线正确。
def _sort_events(
    events:list[CapabilityEvent],
)->tuple[CapabilityEvent,...]:
    indexed=list(enumerate(events))
    indexed.sort(
        key=lambda item:(
            item[1].timestamp,
            item[0],
        )
    )

    return tuple(
        event
        for _,event in indexed
    )

# 五、`InMemoryTraceStore` —— 内存存储实现
# 生产级的内存追踪存储，是默认的运行时实现，支持并发安全、事件去重、容量控制。
class InMemoryTraceStore:
    # 成员	作用
    # max_events_per_run	单请求最大事件数，默认 1000，防止异常请求刷爆内存
    # _events	主存储：run_id → 事件列表
    # _event_ids	去重索引：run_id → 事件 ID 集合，O (1) 判断重复
    # _created_at	创建时间索引：run_id → 第一个事件的时间
    # _lock	可重入读写锁（RLock），保证多线程并发安全

    def __init__(self, max_events_per_run: int = 1000):
        self.max_events_per_run = max_events_per_run
        self._events: dict[str, list[CapabilityEvent]] = {}
        self._event_ids: dict[str, set[str]] = {}
        self._created_at: dict[str, str] = {}
        self._lock = threading.RLock()

    ### 核心方法：`append_event`
    # 追加事件的核心逻辑，完整的校验 + 保护流程：
    # 1. **前置校验**：事件 run_id 不能为空
    # 2. **加锁**：线程安全写入
    # 3. **幂等校验**：event_id 已存在则抛出 `TraceDuplicateEventError`，避免重复写入
    # 4. **容量校验**：当前事件数已达上限则抛出 `TraceCapacityError`，防止内存泄漏
    # 5. **追加事件**：加入事件列表，加入去重集合
    # 6. **记录创建时间**：如果是该 run 的第一个事件，记录创建时间
    def append_event(
        self,
        event: CapabilityEvent,
    ) -> None:
        if not event.run_id:
            raise ValueError(
                "event.run_id cannot be empty"
            )

        with self._lock:
            events = self._events.setdefault(
                event.run_id,
                [],
            )
            event_ids = (
                self._event_ids.setdefault(
                    event.run_id,
                    set(),
                )
            )

            if event.event_id in event_ids:
                raise TraceDuplicateEventError(
                    "duplicate event_id: "
                    f"{event.event_id}"
                )

            if (
                len(events)
                >= self.max_events_per_run
            ):
                raise TraceCapacityError(
                    "run trace capacity exceeded: "
                    f"{event.run_id}"
                )

            events.append(event)
            event_ids.add(event.event_id)

            self._created_at.setdefault(
                event.run_id,
                event.timestamp,
            )

    ### 核心方法：`get_run`
    # 查询单条完整链路：
    # 1. 加锁读取
    # 2. run_id 不存在则抛出 `TraceNotFoundError`
    # 3. 调用 `_sort_events` 按时间排序
    # 4. 计算创建时间、更新时间
    # 5. 组装成标准 `RunTrace` 对象返回
    def get_run(
        self,
        run_id: str,
    ) -> RunTrace:
        with self._lock:
            events = self._events.get(
                run_id
            )

            if events is None:
                raise TraceNotFoundError(
                    run_id
                )

            ordered = _sort_events(
                list(events)
            )
            created_at = (
                self._created_at.get(
                    run_id,
                    utc_now(),
                )
            )
            updated_at = (
                ordered[-1].timestamp
                if ordered
                else created_at
            )

            return RunTrace(
                run_id=run_id,
                events=ordered,
                created_at=created_at,
                updated_at=updated_at,
            )
        
    # `list_runs()`：返回所有 run_id 的有序元组
    def list_runs(
        self,
    ) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                sorted(self._events)
            )

    # `clear()`：清空所有数据，测试 / 重置用
    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._event_ids.clear()
            self._created_at.clear()


## 六、`DatabaseTraceStore` —— 数据库持久化 + 降级实现
# 基于仓库模式的持久化存储实现，**内置降级兜底**：优先读写数据库，数据库故障时自动降级到内存存储，保证业务不中断。
# 设计价值：**生产级高可用**。持久化保证数据不丢，同时数据库故障时，追踪功能不会完全失效，自动降级到内存模式，主业务链路不受影响。
class DatabaseTraceStore:
    def __init__(
        self,
        repository: TraceRepository,
        fallback: TraceStore | None = None,
    ) -> None:
        self.repository = repository
        self.fallback = fallback

    def append_event(
        self,
        event: CapabilityEvent,
    ) -> None:
        try:
            self.repository.append_event(
                event
            )
        except Exception:
            if self.fallback is None:
                raise

            self.fallback.append_event(event)

    def get_run(
        self,
        run_id: str,
    ) -> RunTrace:
        try:
            events = (
                self.repository.get_events(
                    run_id
                )
            )
        except Exception:
            if self.fallback is None:
                raise

            return self.fallback.get_run(
                run_id
            )

        if not events:
            raise TraceNotFoundError(run_id)

        ordered = _sort_events(events)

        return RunTrace(
            run_id=run_id,
            events=ordered,
            created_at=(
                ordered[0].timestamp
            ),
            updated_at=(
                ordered[-1].timestamp
            ),
        )

    def list_runs(
        self,
    ) -> tuple[str, ...]:
        try:
            run_ids = (
                self.repository.list_run_ids()
            )
        except Exception:
            if self.fallback is None:
                raise

            return self.fallback.list_runs()

        return tuple(sorted(set(run_ids)))

    def clear(self) -> None:
        self.repository.clear()

        if self.fallback is not None:
            self.fallback.clear()


# 七、`TraceRecorder` —— 上层记录器封装
# 对上层业务暴露的友好入口，封装存储，提供更简洁的记录接口。
### 作用

# - 屏蔽底层存储细节，上层只需要和记录器打交道
# - 支持单个事件追加，也支持批量追加一整条内部 trace
# - 返回事件本身，方便链式调用
# > 典型用法：RAG 每个阶段处理完，生成事件后调用 `recorder.append(event)`；整条链路跑完，批量把内部 trace 转成标准事件后调用 `append_trace_events`。
class TraceRecorder:
    def __init__(self, store: TraceStore):
        self.store = store
    
    def append(self, event: CapabilityEvent) -> CapabilityEvent:
        self.store.append_event(event)
        return event
    
    def append_trace_events(self, events: tuple[CapabilityEvent, ...]) -> None:
        for event in events:
            self.append(event)


# 业务阶段（重写/检索/上下文/生成）
#         ↓ 生成单个 CapabilityEvent
#     TraceRecorder.append()
#         ↓
#     TraceStore 存储
#         ├─ 内存实现（InMemoryTraceStore）
#         └─ 数据库实现（DatabaseTraceStore + 降级）
#         ↓
#     按 run_id 聚合成 RunTrace
#         ↓
# 查询/监控/排障/审计 调用


## 核心设计亮点总结

# 1. **面向接口设计**：Protocol 定义契约，内存、数据库、Redis 等实现可无缝替换。
# 2. **生产级韧性**：数据库实现内置降级兜底，持久化故障不影响主链路。
# 3. **并发安全**：全量加读写锁，支持多线程并发写入查询。
# 4. **防护机制完备**：事件去重、容量上限、字段校验，防止脏数据和内存泄漏。
# 5. **聚合清晰**：按 run_id 聚合，单请求链路完整可查，时间线有序。
# 6. **分层解耦**：事件模型、存储接口、实现、记录器分层，每层职责单一，易扩展易测试
