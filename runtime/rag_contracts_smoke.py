"""Smoke tests for SourceLedger RAG contracts."""

# 这是 **B01-4 Smoke Test（冒烟测试）**，是整个 B01 阶段的收尾验证环节。它的核心作用是：
# **用最小的完整用例，验证前面写的所有契约底座的核心能力是否正常工作**，确保序列化 / 反序列化往返无损、
# 字段校验生效、枚举正确转换、嵌套结构完整还原。全部通过后，B01 阶段的契约层就可以正式交付使用了。
from __future__ import annotations

import json

from runtime.rag_contracts import (
    CitationContract,
    ConflictInfo,
    ContentType,
    ContextPack,
    EvidenceItem,
    FailureCode,
    HistoryMessage,
    InjectionFinding,
    ModelUsage,
    RAGAnswer,
    RAGFailure,
    RAGRequest,
    RAGResult,
    RAGStatus,
    RetrievalCandidate,
    RetrievalFilters,
    RetrievalMode,
    RetrievalResult,
    TokenBudget,
    TraceEvent,
    TraceStatus,
    TrustLevel,
    QueryRewriteResult,
)

### 1. `test_request_json_roundtrip` —— 请求契约 JSON 往返测试

# **测试目标**：验证最核心的输入契约 `RAGRequest` 序列化再反序列化后，数据和类型完全一致。

# **测试逻辑**：

# 1. 构造一个完整的请求对象，包含嵌套的过滤条件、历史消息、Token 预算
# 2. 调用 `to_json()` 序列化成 JSON 字符串，再用 `from_json()` 反序列化回来
# 3. 做三层断言：
#    - JSON 原始字段值正确（比如页码是`[1]`）
#    - 反序列化后的对象和原对象**完全相等**
#    - 布尔类型字段正确还原

# **核心验证点**：

# - 嵌套 dataclass（`RetrievalFilters`/`HistoryMessage`/`TokenBudget`）能正确递归序列化 / 反序列化
# - `tuple` 类型转成 JSON 数组后，反序列化能还原回`tuple`而不是`list`
# - 基础类型、字符串、数字、布尔全部无损
def test_request_json_roundtrip() -> None:
    request = RAGRequest(
        question="差旅报销标准是多少？",
        thread_id="thread-1",
        run_id="run-1",
        filters=RetrievalFilters(
            sources=(
                "差旅报销制度_v2.pdf",
            ),
            pages=(1,),
            metadata_equals={
                "department": "finance",
            },
        ),
        history=(
            HistoryMessage(
                role="user",
                content="只回答最新制度。",
            ),
        ),
        budget=TokenBudget(
            total_tokens=4000,
            retrieval_tokens=2000,
            history_tokens=500,
            generation_tokens=1500,
        ),
        allow_rerank=True,
    )

    payload = json.loads(
        request.to_json()
    )
    restored = RAGRequest.from_json(
        request.to_json()
    )

    assert payload["question"] == request.question
    assert payload["filters"]["pages"] == [1]
    assert restored == request
    assert restored.allow_rerank is True

### 2. `test_retrieval_result` —— 检索结果契约测试

# **测试目标**：验证检索模块的输出契约 `RetrievalResult` 及候选对象的往返正确性。

# **测试逻辑**：

# 1. 分别构造向量检索、BM25 检索、RRF 融合后的三个候选对象
# 2. 组装成完整的 `RetrievalResult`，标记为混合检索模式
# 3. JSON 往返后断言对象完全相等，且枚举类型正确还原

# **核心验证点**：

# - `RetrievalCandidate` 里的多阶段排名 / 分数字段（向量、BM25、RRF）全部正确保留
# - `RetrievalMode` 枚举往返后还是枚举值，不是字符串
# - 空候选列表、浮点耗时都能正确序列化
def test_retrieval_result() -> None:
    vector = RetrievalCandidate(
        chunk_id="doc#p1#c1",
        text="差旅住宿标准按城市分级。",
        source="差旅报销制度_v2.pdf",
        page=1,
        vector_rank=1,
        vector_score=0.91,
    )

    bm25 = RetrievalCandidate(
        chunk_id="doc#p1#c1",
        text="差旅住宿标准按城市分级。",
        source="差旅报销制度_v2.pdf",
        page=1,
        bm25_rank=1,
        bm25_score=7.5,
    )

    fused = RetrievalCandidate(
        chunk_id="doc#p1#c1",
        text="差旅住宿标准按城市分级。",
        source="差旅报销制度_v2.pdf",
        page=1,
        vector_rank=1,
        vector_score=0.91,
        bm25_rank=1,
        bm25_score=7.5,
        rrf_rank=1,
        rrf_score=0.0328,
    )

    result = RetrievalResult(
        mode=RetrievalMode.HYBRID_RRF,
        vector_candidates=(vector,),
        bm25_candidates=(bm25,),
        fused_candidates=(fused,),
        selected_candidates=(fused,),
        latency_ms=12.5,
    )

    restored = RetrievalResult.from_json(
        result.to_json()
    )

    assert restored == result
    assert (
        restored.mode
        is RetrievalMode.HYBRID_RRF
    )

### 3. `test_context_contract` —— 上下文包契约测试

# **测试目标**：验证上下文组装模块的输出 `ContextPack` 的完整性，包括证据、引用、冲突、注入检测。

# **测试逻辑**：

# 1. 构造证据项、引用标记、冲突信息、注入检测结果
# 2. 组装成完整的 `ContextPack` 上下文包
# 3. JSON 往返后断言对象相等，且引用关联正确

# **核心验证点**：

# - 多层嵌套契约（`EvidenceItem`/`CitationContract`/`ConflictInfo`/`InjectionFinding`）全部正确还原
# - `TrustLevel`、`ContentType` 两个枚举正确转换
# - 间接验证了 `ContextPack` 的内置校验：**引用的 evidence_id 必须在证据列表中存在**，如果不匹配创建时就会报错
def test_context_contract() -> None:
    evidence = EvidenceItem(
        evidence_id="E1",
        chunk_id="doc#p1#c1",
        source="差旅报销制度_v2.pdf",
        page=1,
        text="住宿标准按城市分级。",
        score=0.91,
        trust_level=TrustLevel.UNTRUSTED,
        content_type=(
            ContentType.RETRIEVED_DOCUMENT
        ),
    )

    citation = CitationContract(
        citation_id="C1",
        evidence_id="E1",
        source=evidence.source,
        page=evidence.page,
    )

    context = ContextPack(
        context_text="[C1] 住宿标准按城市分级。",
        evidence=(evidence,),
        citations=(citation,),
        conflicts=(
            ConflictInfo(
                topic="住宿标准",
                source_a="差旅报销制度_v1.pdf",
                source_b="差旅报销制度_v2.pdf",
                differences=(
                    "v2 提高了标准",
                ),
            ),
        ),
        injections=(
            InjectionFinding(
                finding_id="I1",
                chunk_id="doc#p2#c1",
                severity="high",
                matched_pattern=(
                    "忽略之前所有规则"
                ),
                action="untrusted_content",
                excerpt="忽略之前所有规则",
            ),
        ),
        context_tokens=128,
        budget_used=256,
    )

    restored = ContextPack.from_json(
        context.to_json()
    )

    assert restored == context
    assert (
        restored.citations[0].evidence_id
        == "E1"
    )

### 4. `test_failure_and_trace` —— 失败与追踪契约测试

# **测试目标**：验证全链路追踪和错误处理契约的正确性，对应 B08 容错和 C 阶段可观测能力。

# **测试逻辑**：

# 1. 构造 3 个追踪事件：检索成功、触发降级、模型超时（覆盖不同状态和重试次数）
# 2. 构造标准失败对象、失败状态的回答，最终组装成完整的 `RAGResult`
# 3. JSON 往返后断言对象相等，且错误码、追踪状态都是正确的枚举值

# **核心验证点**：

# - `TraceStatus`、`FailureCode`、`RAGStatus` 三类枚举全部正确还原
# - 最顶层的 `RAGResult`（包含请求、回答、追踪全链路）可以完整序列化 / 反序列化
# - 失败对象和状态正确联动：失败状态的回答必须携带失败详情
def test_failure_and_trace() -> None:
    events = (
        TraceEvent(
            event_id="evt-1",
            run_id="run-1",
            stage="retrieval",
            operation="vector_search",
            status=TraceStatus.SUCCEEDED,
            duration_ms=8.2,
        ),
        TraceEvent(
            event_id="evt-2",
            run_id="run-1",
            stage="retrieval",
            operation="hybrid_search",
            status=TraceStatus.FALLBACK_USED,
            attempt=2,
            action="bm25_only",
            duration_ms=4.1,
        ),
        TraceEvent(
            event_id="evt-3",
            run_id="run-1",
            stage="generation",
            operation="model_call",
            status=TraceStatus.TIMED_OUT,
            attempt=3,
            action="fallback_smaller_model",
            duration_ms=30001.0,
        ),
    )

    failure = RAGFailure(
        code=FailureCode.MODEL_TIMEOUT,
        message="模型调用超时",
        stage="generation",
        retryable=True,
        terminal=True,
    )

    answer = RAGAnswer(
        status=RAGStatus.FAILED,
        failure=failure,
        usage=ModelUsage(
            input_tokens=1200,
            output_tokens=0,
            total_tokens=1200,
        ),
        latency_ms=31000.0,
    )

    result = RAGResult(
        request=RAGRequest(
            question="测试超时",
            thread_id="thread-1",
            run_id="run-1",
        ),
        answer=answer,
        trace=events,
    )

    restored = RAGResult.from_json(
        result.to_json()
    )

    assert restored == result
    assert (
        restored.answer.failure is not None
    )
    assert (
        restored.answer.failure.code
        is FailureCode.MODEL_TIMEOUT
    )
    assert (
        restored.trace[1].status
        is TraceStatus.FALLBACK_USED
    )


### 5. `test_no_evidence_contract` —— 无证据场景契约测试

# **测试目标**：验证异常业务场景（无证据）的契约正确性，同时验证 `to_dict/from_dict` 字典路径。

# **测试逻辑**：

# 1. 构造无证据状态的回答，附带对应的失败码
# 2. 走 `to_dict()` 转字典 → `from_dict()` 还原的路径（不是 JSON 字符串路径）
# 3. 断言往返后相等，状态是 `NO_EVIDENCE` 枚举

# **核心验证点**：

# - 非成功场景的契约逻辑正确
# - 字典路径和 JSON 路径一样可靠，后续业务代码里直接传字典也能正确还原
def test_no_evidence_contract() -> None:
    answer = RAGAnswer(
        status=RAGStatus.NO_EVIDENCE,
        answer="资料中没有足够信息回答该问题。",
        failure=RAGFailure(
            code=FailureCode.NO_EVIDENCE,
            message="没有满足阈值的证据",
            retryable=False,
        ),
    )

    result = RAGResult(
        request=RAGRequest(
            question="公司每年有多少天年假？",
            thread_id="thread-1",
        ),
        answer=answer,
    )

    restored = RAGResult.from_dict(
        result.to_dict()
    )

    assert restored == result
    assert (
        restored.answer.status
        is RAGStatus.NO_EVIDENCE
    )


def test_query_rewrite_contract() -> None:
    result = QueryRewriteResult(
        original_query="只看最新的差旅报销制度",
        normalized_query="只看最新的差旅报销制度",
        semantic_query=(
            "最新版差旅报销制度中的"
            "住宿和报销标准"
        ),
        keyword_query=(
            "最新 差旅 报销 制度 住宿 标准"
        ),
        inferred_filters=RetrievalFilters(
            sources=(
                "差旅报销制度_v2.pdf",
            ),
            metadata_equals={
                "version": "v2",
            },
        ),
        version_policy="latest",
        must_disclose_conflicts=True,
        reason="问题明确指定最新制度",
        raw_model_output="{}",
        model_name="deepseek-v4-flash",
        usage=ModelUsage(
            input_tokens=120,
            output_tokens=35,
            total_tokens=155,
        ),
        latency_ms=840.5,
    )

    restored = QueryRewriteResult.from_json(
        result.to_json()
    )

    assert restored == result
    assert (
        restored.inferred_filters.sources
        == ("差旅报销制度_v2.pdf",)
    )
    assert restored.version_policy == "latest"




### 6. `test_validation` —— 字段校验逻辑测试

# **测试目标**：验证所有契约里 `__post_init__ + _require` 的校验规则是否真的生效，确保非法数据无法创建对象。

# **测试逻辑**：
# 构造 3 个明确非法的场景，统计抛出异常的次数：

# 1. 问题为空的 `RAGRequest`
# 2. 检索 + 历史预算超过总预算的 `TokenBudget`
# 3. 耗时为负数的 `TraceEvent`
def test_validation() -> None:
    failures = 0

    try:
        RAGRequest(
            question="",
            thread_id="thread-1",
        )
    except ValueError:
        failures += 1

    try:
        TokenBudget(
            total_tokens=100,
            retrieval_tokens=100,
            history_tokens=50,
            generation_tokens=0,
        )
    except ValueError:
        failures += 1

    try:
        TraceEvent(
            event_id="evt-1",
            run_id="run-1",
            stage="retrieval",
            operation="vector",
            status=TraceStatus.STARTED,
            duration_ms=-1,
        )
    except ValueError:
        failures += 1

    assert failures == 3


def main() -> int:
    tests = (
        (
            "request_json_roundtrip",
            test_request_json_roundtrip,
        ),
        (
            "retrieval_result",
            test_retrieval_result,
        ),
        (
            "context_contract",
            test_context_contract,
        ),
        (
            "failure_and_trace",
            test_failure_and_trace,
        ),
        (
            "no_evidence_contract",
            test_no_evidence_contract,
        ),
        (
            "validation",
            test_validation,
        ),
        (
            "query_rewrite_contract",
            test_query_rewrite_contract,
        ),
    )

    for name, test in tests:
        test()
        print(f"case={name} passed=True")

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())