# 这是 ** RAG 运行时主文件**，作用是把独立的 `QueryRewriter` 封装进标准的 RAG 运行时流程，补充全链路追踪、运行 ID 管理，输出标准化的阶段结果，是连接上游请求和下游检索的中间层。
from __future__ import annotations

import time
# - `ThreadPoolExecutor`：线程池，实现两路检索真正并行执行，总耗时等于慢的那一路，而不是两路相加
# - 导入两个检索器实现，运行时内部持有并调用
from concurrent.futures import (
    ThreadPoolExecutor,
)
from dataclasses import dataclass, replace
from uuid import uuid4

from runtime.B02_query_rewriter import (
    QueryRewriter,
)
from runtime.rag_contracts import (
    ContractModel,
    QueryRewriteResult,
    RAGRequest,
    RetrievalMode,
    RetrievalResult,
    TraceEvent,
    TraceStatus,
    ContextPack,
    RAGAnswer,
    RAGStatus,
)
from runtime.retrieval.bm25 import (
    BM25Retriever,
)
from runtime.retrieval.vector import (
    VectorRetriever,
)
from runtime.retrieval.rrf import fuse_rrf
from runtime.retrieval.reranker import (
    Reranker,
    RerankerConfig,
    should_rerank,
)
from runtime.context.packing import (
    pack_runtime_context,
)
from runtime.generation import (
    AnswerGenerator,
)
from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)
from runtime.resilience.retrieval_policy import (
    ResilientRetriever,
    RetrievalExecution,
)
# 二、`QueryRewriteRun` 阶段结果契约
# 这是 **B02 阶段的完整输出包**，继承 `ContractModel` 自带序列化能力。
# 字段	用途
# request	处理后的请求对象（补充了 run_id），原样传递给下游
# rewrite	查询重写的完整结果，包含多版本查询、过滤器、降级标记等
# trace	本阶段产生的所有追踪事件，后续会合并到全链路追踪里
# 设计意图：把「请求 + 业务结果 + 追踪日志」打包成一个整体，下游检索阶段只需要接收这个对象，就能拿到所有需要的信息，不需要分别传多个参数。
@dataclass
class QueryRewriteRun(ContractModel):
    request: RAGRequest
    rewrite: QueryRewriteResult
    trace: tuple[TraceEvent, ...] = ()

# 新增 `RetrievalRun` 阶段结果契约
# 和 `QueryRewriteRun` 对应，是**检索阶段的完整输出包**：

# - 原样携带请求、重写结果，向下游传递
# - 包含本阶段的核心产出 `RetrievalResult`
# - 聚合了从请求开始到检索结束的所有追踪事件，链路不中断
@dataclass
class RetrievalRun(ContractModel):
    request: RAGRequest
    rewrite: QueryRewriteResult
    retrieval: RetrievalResult
    trace: tuple[TraceEvent, ...] = ()

@dataclass
class ContextRun(ContractModel):
    request: RAGRequest
    rewrite: QueryRewriteResult
    retrieval: RetrievalResult
    context: ContextPack
    trace: tuple[TraceEvent, ...] = ()

@dataclass
class GenerationRun(ContractModel):
    request: RAGRequest
    rewrite: QueryRewriteResult
    retrieval: RetrievalResult
    context: ContextPack
    answer: RAGAnswer
    trace: tuple[TraceEvent, ...] = ()

### 三、`RAGRuntime` 运行时核心类
# 这是整个 RAG 运行时的主类，后续 B03~B08 的所有阶段都会往这个类里加方法。
# 当前 B02 阶段只实现了 `prepare`（查询预处理）方法。
class RAGRuntime:
    def __init__(
        self,
        rewriter: QueryRewriter | None = None,
        vector_retriever: (
            VectorRetriever | None
        ) = None,
        bm25_retriever: (
            BM25Retriever | None
        ) = None,
        rrf_k: int = 60,
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0,
        reranker: Reranker | None = None,
        reranker_config: (
            RerankerConfig | None
        ) = None,
        generator: AnswerGenerator | None = None,
        
    ) -> None:
            self.rewriter = (
                rewriter
                if rewriter is not None
                else QueryRewriter()
            )
            self.vector_retriever = (
                vector_retriever
            )
            self.bm25_retriever = (
                bm25_retriever
            )
            self.rrf_k = rrf_k
            self.vector_weight = (
                vector_weight
            )
            self.bm25_weight = (
                bm25_weight
            )
            # BM25 索引同步缓存。记录上次构建索引时向量库的文档数量，用来判断语料有没有更新，要不要重建索引
            self._bm25_collection_count = -1
            self.reranker = (
                reranker
                if reranker is not None
                else Reranker(
                    config=reranker_config
                )
            )
            self.generator = (
                generator
                if generator is not None
                else AnswerGenerator()
            )
            self.vector_policy: (
                ResilientRetriever | None
            ) = None
            self.bm25_policy: (
                ResilientRetriever | None
            ) = None
     # 2. `prepare` 核心方法
    def prepare(
        self,
        request:RAGRequest,
    )->QueryRewriteRun:
        # 计时与运行 ID 生成
        # - `started`：高精度计时起点，统计整个 prepare 阶段的总耗时
        # - `run_id`：单次请求的唯一追踪 ID。如果请求里已经带了就复用，没有就用 UUID 自动生成
        # - `replace(request, run_id=run_id)`：生成一个新的 `RAGRequest` 对象，把 `run_id` 填进去。**不直接修改原对象**，符合契约的不可变设计，避免副作用
        started=time.perf_counter()
        run_id=request.run_id or f"run-{uuid4().hex}"
        request=replace(
            request,
            run_id=run_id
        )

        # 请求接收追踪事件
        # 生成第一个追踪事件，标记「请求已接收、完成规范化」。

        # - `event_id`：用 `run_id:事件名` 保证全局唯一
        # - `stage`：归属阶段为 `query_rewrite`
        # - `operation`：具体操作是规范化请求
        # - `action`：具体动作是保留原始并做规范化
        # - `metadata`：记录问题长度等基础信息，用于统计分析
        received=TraceEvent(
            event_id=f"{run_id}:request",
            run_id=run_id,
            stage="query_rewrite",
            operation="normalize_request",
            status=TraceStatus.SUCCEEDED,
            attempt=1,
            action="keep_original_and_normalize",
            duration_ms=0.0,
            metadata={
                "question_length": len(
                    request.question
                ),
            },
        )

        # 执行查询重写
        # 调用重写器执行核心逻辑，拿到 `QueryRewriteResult` 结果。
        rewrite=self.rewriter.rewrite(request)

        # 状态判断与动作映射
        # 根据重写结果是否触发降级，映射对应的追踪状态和动作标签：
        # - 降级：状态 `FALLBACK_USED`，动作 `deterministic_fallback`（确定性规则降级）
        # - 正常：状态 `SUCCEEDED`，动作 `deepseek_structured_json`（DeepSeek 结构化 JSON 输出）
        if rewrite.fallback_used:
            rewrite_status = TraceStatus.FALLBACK_USED
            rewrite_action = "deterministic_fallback"
        else:
            rewrite_status = TraceStatus.SUCCEEDED
            rewrite_action = "deepseek_structured_json"

        # 重写完成追踪事件
        # 生成第二个追踪事件，记录重写的完整执行信息。

        # - `duration_ms`：重写本身的耗时，取自重写结果
        # - `metadata` 里记录了完整的上下文：模型名、版本策略、冲突披露开关、Token 用量、降级原因、**整个 prepare 阶段的总耗时**
        # - 所有信息都沉淀到追踪事件里，后续排查问题不需要复现，看 trace 就够了
        rewrite_event = TraceEvent(
            event_id=f"{run_id}:rewrite",
            run_id=run_id,
            stage="query_rewrite",
            operation="llm_rewrite",
            status=rewrite_status,
            attempt=1,
            action=rewrite_action,
            duration_ms=rewrite.latency_ms,
            metadata={
                "model_name": (
                    rewrite.model_name
                ),
                "version_policy": (
                    rewrite.version_policy
                ),
                "must_disclose_conflicts": (
                    rewrite
                    .must_disclose_conflicts
                ),
                "usage": (
                    rewrite.usage.to_dict()
                ),
                "fallback_reason": (
                    rewrite.fallback_reason
                ),
                "elapsed_ms": round(
                    (
                        time.perf_counter()
                        - started
                    )
                    * 1000,
                    2,
                ),
            },
        )
        # 把「更新后的请求 + 重写结果 + 2 个追踪事件」打包成 `QueryRewriteRun` 返回。
        return QueryRewriteRun(
            request=request,
            rewrite=rewrite,
            trace=(
                received,
                rewrite_event,
            ),
        )

    ### 4. `retrieve` 核心方法（重点）
    # 输入是上一阶段的 `QueryRewriteRun`，输出是 `RetrievalRun`，完整实现并行检索、自动同步、故障降级、链路追踪。
    def retrieve(
        self,
        prepared:QueryRewriteRun,
        candidate_k:int=20,
    )->RetrievalRun:
        started=time.perf_counter()
        run_id = (
            prepared.request.run_id
            or prepared.rewrite.original_query
        )

        if self.vector_retriever is None:
            self.vector_retriever=VectorRetriever()
        if self.bm25_retriever is None:
            self.bm25_retriever=BM25Retriever()

        # ② BM25 索引自动同步
        # 这是非常关键的设计：**BM25 的语料自动和向量库保持一致**。
        # - 每次检索前对比向量库的文档总数
        # - 和缓存的计数不一样，说明语料有新增 / 删除，就重新从 Chroma 拉取全量文档构建 BM25 索引
        # - 同步完成后更新缓存计数
        # > 价值：永远不用手动维护两份语料，向量库是唯一真相源，BM25 自动跟随更新，彻底避免两路检索语料不一致的问题。
        collection=self.vector_retriever.collection
        collection_count=int(collection.count())

        if self._bm25_collection_count != collection_count:
            self.bm25_retriever.fit_collection(collection)
            self._bm25_collection_count=collection_count

        filters = (
            prepared.rewrite.inferred_filters
        )

        if self.vector_policy is None:
            self.vector_policy = (
                ResilientRetriever(
                    retriever=(
                        self.vector_retriever
                    ),
                    operation_name=(
                        "retrieval.vector"
                    ),
                    timeout_policy=(
                        TimeoutPolicy(
                            timeout_ms=60000
                        )
                    ),
                    retry_policy=RetryPolicy(
                        max_attempts=2,
                        base_delay_ms=200,
                        max_delay_ms=2000,
                        jitter_ratio=0.1,
                    ),
                )
            )

        if self.bm25_policy is None:
            self.bm25_policy = (
                ResilientRetriever(
                    retriever=(
                        self.bm25_retriever
                    ),
                    operation_name=(
                        "retrieval.bm25"
                    ),
                    timeout_policy=(
                        TimeoutPolicy(
                            timeout_ms=10000
                        )
                    ),
                    retry_policy=RetryPolicy(
                        max_attempts=2,
                        base_delay_ms=150,
                        max_delay_ms=1500,
                        jitter_ratio=0.1,
                    ),
                )
            )

        def run_vector() -> RetrievalExecution:
            return self.vector_policy.search(
                query=(
                    prepared.rewrite
                    .semantic_query
                ),
                filters=filters,
                top_k=candidate_k,
            )

        def run_bm25() -> RetrievalExecution:
            return self.bm25_policy.search(
                query=(
                    prepared.rewrite
                    .keyword_query
                ),
                filters=filters,
                top_k=candidate_k,
            )

        # # ⑤ 线程池并行执行
        # - 开 2 个线程同时提交两路检索任务
        # - 等待两路都执行完成，拿到各自的结果
        # - **性能收益**：总耗时 = 较慢那一路的耗时，而不是两路耗时相加，典型的并行优化
        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:
            vector_future = (
                executor.submit(run_vector)
            )
            bm25_future = (
                executor.submit(run_bm25)
            )

            vector_execution = (
                vector_future.result()
            )
            bm25_execution = (
                bm25_future.result()
            )

        vector_candidates = list(
            vector_execution.candidates
        )
        bm25_candidates = list(
            bm25_execution.candidates
        )

        vector_latency = (
            vector_execution.latency_ms
        )
        bm25_latency = (
            bm25_execution.latency_ms
        )

        vector_error = (
            vector_execution.error
        )
        bm25_error = (
            bm25_execution.error
        )

        errors: dict[str, str] = {}

        if vector_error:
            errors["vector"] = vector_error

        if bm25_error:
            errors["bm25"] = bm25_error

        source_fallbacks: list[str] = []

        if (
            vector_execution.source
            not in {
                "retrieval.vector",
                "failed",
            }
        ):
            source_fallbacks.append(
                "vector:"
                f"{vector_execution.source}"
            )

        if (
            bm25_execution.source
            not in {
                "retrieval.bm25",
                "failed",
            }
        ):
            source_fallbacks.append(
                "bm25:"
                f"{bm25_execution.source}"
            )

        if len(errors) == 2:
            fallback_used = "none"
        elif "vector" in errors:
            fallback_used = "bm25_only"
        elif "bm25" in errors:
            fallback_used = "vector_only"
        elif source_fallbacks:
            fallback_used = ",".join(
                source_fallbacks
            )
        else:
            fallback_used = ""

        fused_candidates, rrf_latency = (
            fuse_rrf(
                vector_candidates=(
                    vector_candidates
                ),
                bm25_candidates=(
                    bm25_candidates
                ),
                k=self.rrf_k,
                vector_weight=(
                    self.vector_weight
                ),
                bm25_weight=(
                    self.bm25_weight
                ),
                top_k=candidate_k,
            )
        )

        (
            rerank_triggered,
            rerank_reason,
        ) = should_rerank(
            candidates=fused_candidates,
            allow_rerank=(
                prepared.request
                .allow_rerank
            ),
            query_ambiguous=False,
            config=self.reranker.config,
        )

        reranked_candidates: list = []

        if rerank_triggered:
            rerank_result = (
                self.reranker.rerank(
                    question=(
                        prepared.rewrite
                        .original_query
                    ),
                    candidates=(
                        fused_candidates
                    ),
                    top_k=candidate_k,
                )
            )

            reranked_candidates = list(
                rerank_result.candidates
            )

            if (
                rerank_result.backend
                == "noop"
                or rerank_result.error
            ):
                rerank_status = (
                    TraceStatus.FALLBACK_USED
                )
                rerank_action = (
                    "rrf_noop_fallback"
                )
            else:
                rerank_status = (
                    TraceStatus.SUCCEEDED
                )
                rerank_action = (
                    "cross_encoder"
                )

            rerank_event = TraceEvent(
                event_id=f"{run_id}:rerank",
                run_id=run_id,
                stage="retrieval",
                operation="rerank",
                status=rerank_status,
                attempt=1,
                action=rerank_action,
                duration_ms=(
                    rerank_result.latency_ms
                ),
                metadata={
                    "trigger_reason": (
                        rerank_reason
                    ),
                    "backend": (
                        rerank_result.backend
                    ),
                    "model_name": (
                        rerank_result.model_name
                    ),
                    "load_ms": (
                        rerank_result.load_ms
                    ),
                    "input_count": len(
                        fused_candidates
                    ),
                    "output_count": len(
                        reranked_candidates
                    ),
                    "error": (
                        rerank_result.error
                    ),
                },
            )

        else:
            rerank_event = TraceEvent(
                event_id=f"{run_id}:rerank",
                run_id=run_id,
                stage="retrieval",
                operation="rerank",
                status=TraceStatus.SKIPPED,
                attempt=1,
                action=rerank_reason,
                duration_ms=0.0,
                metadata={
                    "trigger_reason": (
                        rerank_reason
                    ),
                    "input_count": len(
                        fused_candidates
                    ),
                },
            )

        if errors or source_fallbacks:
            mode = (
                RetrievalMode
                .HYBRID_FALLBACK
            )
        elif rerank_triggered:
            mode = (
                RetrievalMode
                .HYBRID_RERANK
            )
        else:
            mode = RetrievalMode.HYBRID_RRF


        vector_status = (
            TraceStatus.FAILED
            if vector_error
            else TraceStatus.SUCCEEDED
        )
        bm25_status = (
            TraceStatus.FAILED
            if bm25_error
            else TraceStatus.SUCCEEDED
        )

        vector_event = TraceEvent(
            event_id=f"{run_id}:vector",
            run_id=run_id,
            stage="retrieval",
            operation="vector_search",
            status=vector_status,
            attempt=1,
            action="chroma_vector",
            duration_ms=vector_latency,
            metadata={
                "candidate_count": len(
                    vector_candidates
                ),
                "semantic_query": (
                    prepared.rewrite
                    .semantic_query
                ),
                "error": vector_error,
                "execution_source": (
                    vector_execution.source
                ),
                "attempts": (
                    vector_execution.attempts
                ),
                "fallback_attempts": [
                    {
                        "source": item.source,
                        "error": item.error,
                    }
                    for item in (
                        vector_execution
                        .fallback_attempts
                    )
                ],
            },
        )

        bm25_event = TraceEvent(
            event_id=f"{run_id}:bm25",
            run_id=run_id,
            stage="retrieval",
            operation="bm25_search",
            status=bm25_status,
            attempt=1,
            action="bm25_keyword",
            duration_ms=bm25_latency,
            metadata={
                "candidate_count": len(
                    bm25_candidates
                ),
                "keyword_query": (
                    prepared.rewrite
                    .keyword_query
                ),
                "error": bm25_error,
                "execution_source": (
                    bm25_execution.source
                ),
                "attempts": (
                    bm25_execution.attempts
                ),
                "fallback_attempts": [
                    {
                        "source": item.source,
                        "error": item.error,
                    }
                    for item in (
                        bm25_execution
                        .fallback_attempts
                    )
                ],
            },
        )

        total_latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        parallel_status = (
            TraceStatus.FALLBACK_USED
            if errors
            else TraceStatus.SUCCEEDED
        )

        parallel_event = TraceEvent(
            event_id=(
                f"{run_id}:parallel_retrieval"
            ),
            run_id=run_id,
            stage="retrieval",
            operation="parallel_retrieval",
            status=parallel_status,
            attempt=1,
            action=(
                fallback_used
                or "vector_and_bm25"
            ),
            duration_ms=total_latency_ms,
            metadata={
                "vector_latency_ms": (
                    vector_latency
                ),
                "bm25_latency_ms": (
                    bm25_latency
                ),
                "vector_count": len(
                    vector_candidates
                ),
                "bm25_count": len(
                    bm25_candidates
                ),
                "errors": errors,
            },
        )
        rrf_status = (
            TraceStatus.FALLBACK_USED
            if errors
            else TraceStatus.SUCCEEDED
        )

        rrf_event = TraceEvent(
            event_id=f"{run_id}:rrf",
            run_id=run_id,
            stage="retrieval",
            operation="rrf_fusion",
            status=rrf_status,
            attempt=1,
            action=(
                fallback_used
                or "reciprocal_rank_fusion"
            ),
            duration_ms=rrf_latency,
            metadata={
                "k": self.rrf_k,
                "vector_weight": (
                    self.vector_weight
                ),
                "bm25_weight": (
                    self.bm25_weight
                ),
                "vector_count": len(
                    vector_candidates
                ),
                "bm25_count": len(
                    bm25_candidates
                ),
                "fused_count": len(
                    fused_candidates
                ),
            },
        )

        total_latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        retrieval = RetrievalResult(
            mode=mode,
            vector_candidates=tuple(
                vector_candidates
            ),
            bm25_candidates=tuple(
                bm25_candidates
            ),
            fused_candidates=tuple(
                fused_candidates
            ),
            latency_ms=total_latency_ms,
            fallback_used=fallback_used,
            reranked_candidates=tuple(
                reranked_candidates
            ),
            metadata={
                "errors": errors,
                "vector_latency_ms": (
                    vector_latency
                ),
                "bm25_latency_ms": (
                    bm25_latency
                ),
                "rrf_latency_ms": (
                    rrf_latency
                ),
                "rrf_k": self.rrf_k,
                "rerank_triggered": (
                    rerank_triggered
                ),
                "rerank_reason": (
                    rerank_reason
                ),
                "rerank_latency_ms": (
                    rerank_event.duration_ms
                ),
                "vector_execution_source": (
                    vector_execution.source
                ),
                "bm25_execution_source": (
                    bm25_execution.source
                ),
                "vector_attempts": (
                    vector_execution.attempts
                ),
                "bm25_attempts": (
                    bm25_execution.attempts
                ),
                "source_fallbacks": (
                    source_fallbacks
                ),
            },
        )

        return RetrievalRun(
            request=prepared.request,
            rewrite=prepared.rewrite,
            retrieval=retrieval,
            trace=(
                *prepared.trace,
                vector_event,
                bm25_event,
                parallel_event,
                rrf_event,
                rerank_event,
            ),
        )

    # 上下文打包
    def pack_context(
        self,
        retrieval_run: RetrievalRun,
        retrieval_budget: int = 1800,
        max_chunk_per_page: int = 2,
        max_chunk_per_parent: int = 2,
    ) -> ContextRun:
        # ① 计时 + 自动选择最优候选源
        started = time.perf_counter()

        if (
            retrieval_run.retrieval
            .reranked_candidates
        ):
            candidates = (
                retrieval_run.retrieval
                .reranked_candidates
            )
            source_stage = "rerank"
        else:
            candidates = (
                retrieval_run.retrieval
                .fused_candidates
            )
            source_stage = "rrf"

        context = pack_runtime_context(
            candidates=candidates,
            retrieval_budget=(
                retrieval_budget
            ),
            max_chunk_per_page=(
                max_chunk_per_page
            ),
            max_chunk_per_parent=(
                max_chunk_per_parent
            ),
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        run_id = (
            retrieval_run.request.run_id
            or retrieval_run.rewrite.original_query
        )

        context_event = TraceEvent(
            event_id=f"{run_id}:context_pack",
            run_id=run_id,
            stage="context",
            operation="context_pack",
            status=TraceStatus.SUCCEEDED,
            attempt=1,
            action="deduplicate_and_budget",
            duration_ms=latency_ms,
            metadata={
                "source_stage": (
                    source_stage
                ),
                "input_count": len(
                    candidates
                ),
                "selected_count": len(
                    context.evidence
                ),
                "duplicate_text_count": (
                    context
                    .duplicate_text_count
                ),
                "context_tokens": (
                    context.context_tokens
                ),
                "budget": retrieval_budget,
                "citation_count": len(
                    context.citations
                ),
                "conflict_count": len(
                    context.conflicts
                ),
                "injection_count": len(
                    context.injections
                ),
                "source_diversity": (
                    context.source_diversity
                ),
            },
        )

        return ContextRun(
            request=retrieval_run.request,
            rewrite=retrieval_run.rewrite,
            retrieval=retrieval_run.retrieval,
            context=context,
            trace=(
                *retrieval_run.trace,
                context_event,
            ),
        )

    def generate(
        self,
        context_run: ContextRun,
    ) -> GenerationRun:
        result = self.generator.generate(
            question=(
                context_run.request.question
            ),
            context=context_run.context,
        )

        answer = result.answer

        if (
            answer.status
            is RAGStatus.SUCCEEDED
        ):
            generation_status = (
                TraceStatus.SUCCEEDED
            )
            generation_action = (
                "deepseek_answer"
            )
        elif (
            answer.status
            is RAGStatus.NO_EVIDENCE
        ):
            generation_status = (
                TraceStatus.REJECTED
            )
            generation_action = (
                "no_evidence_refusal"
            )
        else:
            generation_status = (
                TraceStatus.FAILED
            )
            generation_action = (
                "generation_failed"
            )

        run_id = (
            context_run.request.run_id
            or context_run.rewrite.original_query
        )

        generation_event = TraceEvent(
            event_id=f"{run_id}:generation",
            run_id=run_id,
            stage="generation",
            operation="model_call",
            status=generation_status,
            attempt=1,
            action=generation_action,
            duration_ms=answer.latency_ms,
            metadata={
                "model_name": (
                    result.model_name
                ),
                "usage": (
                    answer.usage.to_dict()
                ),
                "cited_ids": list(
                    result.cited_ids
                ),
                "invalid_citation_ids": (
                    list(
                        result
                        .invalid_citation_ids
                    )
                ),
                "citation_count": len(
                    answer.citations
                ),
                "failure_code": (
                    answer.failure.code.value
                    if answer.failure
                    else ""
                ),
                "failure_message": (
                    answer.failure.message
                    if answer.failure
                    else ""
                ),
            },
        )

        return GenerationRun(
            request=context_run.request,
            rewrite=context_run.rewrite,
            retrieval=context_run.retrieval,
            context=context_run.context,
            answer=answer,
            trace=(
                *context_run.trace,
                generation_event,
            ),
        )


