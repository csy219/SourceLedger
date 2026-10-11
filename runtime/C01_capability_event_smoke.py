"""Smoke test for C01 CapabilityEvent."""
# 这是 **C01 标准能力事件模型的冒烟测试套件**，专门验证上一节 `CapabilityEvent` 的核心能力：序列化兼容性、双向无损转换、批量处理、全状态支持、强校验边界，确保可观测性层的数据基础准确可靠，是整个事件体系的质量闸门。
# 下面逐个测试用例拆解，对应到事件模型的功能点。

# ## 整体说明
# - 测试层级：单元级冒烟测试
# - 覆盖范围：JSON 序列化往返、内部 trace 双向转换、批量转换、状态枚举覆盖、强校验规则
# - 设计原则：每个用例验证一个独立能力点，全部通过才算事件模型可用
# - 核心价值：事件是监控、审计、排障的基础，数据格式错、丢字段、校验失效会导致整个可观测体系失真，所以用全维度测试兜底。
# ## 测试用例逐一拆解

# ### 1. `test_json_roundtrip()` —— JSON 序列化往返测试
# **核心目的**：验证 `CapabilityEvent` 可以完整地序列化成 JSON，再反序列化还原后和原对象完全一致，嵌套元数据也不丢失、不错位。
# #### 执行逻辑
# 1. 构造一个完整的 `CapabilityEvent`，包含嵌套的 counts、weights、tags 等复杂元数据
# 2. 调用 `.to_json()` 序列化成 JSON 字符串
# 3. 调用 `CapabilityEvent.from_json()` 反序列化还原
# 4. 断言还原后的对象和原对象完全相等
# 5. 断言深层嵌套的元数据值正确
# #### 对应能力
# → 继承自 `ContractModel` 的标准序列化 / 反序列化能力
# #### 为什么要测
# 事件要输出到日志、消息队列、监控系统，**序列化是必经之路**。如果往返不一致、丢字段、嵌套结构损坏，外部系统拿到的就是脏数据，整条可观测链路就失效了。

# ### 2. `test_trace_conversion()` —— Trace 双向无损转换测试
# **核心目的**：验证内部 `TraceEvent` 和标准 `CapabilityEvent` 可以双向互相转换，所有字段一一对应，转换过程零信息丢失。
# #### 执行逻辑
# 1. 构造一个完整的内部 `TraceEvent`
# 2. 用 `from_trace_event()` 转成 `CapabilityEvent`
# 3. 再用 `to_trace_event()` 转回 `TraceEvent`
# 4. 逐字段断言：事件 ID、run_id、阶段、操作、状态、尝试次数、动作、耗时、元数据，全部完全一致
# #### 对应能力
# → `from_trace_event()` / `to_trace_event()` 双向转换方法
# #### 为什么要测
# 这是事件适配层的核心功能。如果转换丢字段、错状态，内部 trace 导出到外部就会失真；反过来外部事件转回内部处理也会出错。必须保证双向无损。

# ### 3. `test_events_from_trace()` —— 批量链路转换测试
# **核心目的**：验证整条链路的 trace 元组，可以一次性批量转换成标准事件列表，数量、类型、状态都正确。
# #### 执行逻辑
# 1. 构造一条包含 3 个事件的 trace 链路：向量检索、BM25 检索、模型调用失败
# 2. 调用 `events_from_trace()` 批量转换
# 3. 断言：
#    - 转换后数量 = 3
#    - 所有元素都是 `CapabilityEvent` 类型
#    - 最后一个事件的状态正确保留为 `FAILED`
# #### 对应能力
# → `events_from_trace()` 批量转换工具函数
# #### 为什么要测
# 实际业务中都是整条 trace 一次性导出，不是逐个转换。批量转换功能必须正确，且保留每个事件的所有属性。

# ### 4. `test_status_coverage()` —— 全状态枚举覆盖测试
# **核心目的**：验证所有 `TraceStatus` 枚举值，都可以正常用于 `CapabilityEvent`，不会出现类型不兼容、赋值报错。
# #### 执行逻辑
# 1. 遍历所有状态枚举：成功、失败、跳过、重试中、降级使用、超时、熔断打开、拒绝
# 2. 每个状态都构造一个事件
# 3. 断言所有事件都创建成功，状态集合和原枚举集合完全一致
# #### 为什么要测
# 内部 trace 会产生各种状态的事件，导出到标准事件时必须全部支持，不能出现某些状态无法导出的情况。

# ### 5. `test_validation()` —— 强校验规则测试
# **核心目的**：验证 `__post_init__` 的字段校验逻辑确实生效，非法构造会被拦截，保证对外输出的事件都是合法的。
# #### 执行逻辑
# 构造 4 种非法场景，每种都应该抛出 `ValueError`：
# 1. **空 run_id**：run_id 传空字符串
# 2. **空 stage**：stage 传空字符串
# 3. **尝试次数为 0**：attempt = 0（规则要求 ≥ 1）
# 4. **耗时为负**：duration_ms = -1.0（规则要求 ≥ 0）
# 最后断言失败次数 = 4，说明 4 种校验全部生效。
# #### 对应能力
# → `__post_init__` 字段强校验
# #### 为什么要测
# 对外事件必须保证数据质量。如果校验不生效，空字段、非法值的事件流到外部监控系统，会造成统计错误、告警失效、审计不合规。

# ## 整体设计总结
# 1. **五维全覆盖**：序列化、双向转换、批量处理、状态兼容、边界校验，覆盖事件模型所有核心能力点。
# 2. **面向生产**：重点测了序列化、校验、无损转换这些生产环境最容易出问题的地方，而不是只测正常流程。
# 3. **边界明确**：合法场景和非法场景都测，既保证正常能用，也保证异常能拦。
# 4. **基础支撑**：事件模型是整个可观测体系的地基，这套测试就是地基的质量验收，确保上层监控、审计、排障都建立在可靠的数据基础上。
from __future__ import annotations

from runtime.capability_events import (
    CapabilityEvent,
    events_from_trace,
)
from runtime.rag_contracts import (
    TraceEvent,
    TraceStatus,
)


def test_json_roundtrip() -> None:
    event = CapabilityEvent(
        event_id="evt-c01-1",
        run_id="run-c01",
        stage="retrieval",
        operation="rrf_fusion",
        status=TraceStatus.SUCCEEDED,
        attempt=1,
        action="reciprocal_rank_fusion",
        duration_ms=1.25,
        metadata={
            "counts": {
                "vector": 13,
                "bm25": 8,
                "rrf": 13,
            },
            "weights": {
                "vector": 1.0,
                "bm25": 1.0,
            },
            "tags": [
                "retrieval",
                "hybrid",
            ],
        },
    )

    restored = CapabilityEvent.from_json(
        event.to_json()
    )

    assert restored == event
    assert (
        restored.metadata["counts"]["rrf"]
        == 13
    )

    print(
        "case=json_roundtrip passed=True"
    )


def test_trace_conversion() -> None:
    trace = TraceEvent(
        event_id="trace-1",
        run_id="run-c01",
        stage="context",
        operation="context_pack",
        status=TraceStatus.SUCCEEDED,
        attempt=2,
        action="deduplicate_and_budget",
        duration_ms=4.5,
        metadata={
            "selected_count": 13,
            "tokens": 1400,
        },
    )

    event = (
        CapabilityEvent
        .from_trace_event(trace)
    )

    restored_trace = (
        event.to_trace_event()
    )

    assert event.event_id == trace.event_id
    assert event.run_id == trace.run_id
    assert event.stage == trace.stage
    assert (
        event.operation
        == trace.operation
    )
    assert event.status is trace.status
    assert event.attempt == trace.attempt
    assert event.action == trace.action
    assert (
        event.duration_ms
        == trace.duration_ms
    )
    assert (
        event.metadata
        == trace.metadata
    )

    assert (
        restored_trace.event_id
        == trace.event_id
    )
    assert (
        restored_trace.metadata
        == trace.metadata
    )

    print(
        "case=trace_conversion passed=True"
    )


def test_events_from_trace() -> None:
    trace = (
        TraceEvent(
            event_id="trace-1",
            run_id="run-c01",
            stage="retrieval",
            operation="vector_search",
            status=TraceStatus.SUCCEEDED,
        ),
        TraceEvent(
            event_id="trace-2",
            run_id="run-c01",
            stage="retrieval",
            operation="bm25_search",
            status=TraceStatus.SUCCEEDED,
        ),
        TraceEvent(
            event_id="trace-3",
            run_id="run-c01",
            stage="generation",
            operation="model_call",
            status=TraceStatus.FAILED,
        ),
    )

    events = events_from_trace(trace)

    assert len(events) == 3
    assert all(
        isinstance(
            event,
            CapabilityEvent,
        )
        for event in events
    )
    assert (
        events[-1].status
        is TraceStatus.FAILED
    )

    print(
        "case=events_from_trace passed=True"
    )


def test_status_coverage() -> None:
    statuses = (
        TraceStatus.SUCCEEDED,
        TraceStatus.FAILED,
        TraceStatus.SKIPPED,
        TraceStatus.RETRYING,
        TraceStatus.FALLBACK_USED,
        TraceStatus.TIMED_OUT,
        TraceStatus.CIRCUIT_OPEN,
        TraceStatus.REJECTED,
    )

    events = [
        CapabilityEvent(
            event_id=f"evt-{status.value}",
            run_id="run-c01",
            stage="test",
            operation="status_coverage",
            status=status,
        )
        for status in statuses
    ]

    assert len(events) == len(statuses)
    assert {
        event.status
        for event in events
    } == set(statuses)

    print(
        "case=status_coverage passed=True"
    )


def test_validation() -> None:
    failures = 0

    try:
        CapabilityEvent(
            event_id="evt-1",
            run_id="",
            stage="test",
            operation="validation",
        )
    except ValueError:
        failures += 1

    try:
        CapabilityEvent(
            event_id="evt-2",
            run_id="run-c01",
            stage="",
            operation="validation",
        )
    except ValueError:
        failures += 1

    try:
        CapabilityEvent(
            event_id="evt-3",
            run_id="run-c01",
            stage="test",
            operation="validation",
            attempt=0,
        )
    except ValueError:
        failures += 1

    try:
        CapabilityEvent(
            event_id="evt-4",
            run_id="run-c01",
            stage="test",
            operation="validation",
            duration_ms=-1.0,
        )
    except ValueError:
        failures += 1

    assert failures == 4

    print(
        "case=validation passed=True"
    )


def main() -> int:
    test_json_roundtrip()
    test_trace_conversion()
    test_events_from_trace()
    test_status_coverage()
    test_validation()

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())