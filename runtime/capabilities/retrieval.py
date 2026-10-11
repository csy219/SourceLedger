"""Thin capability adapters over RAGRuntime."""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any
from uuid import uuid4

from runtime.api.capabilities import (
    CapabilityDefinition,
    CapabilityDescriptor,
    CapabilityRegistry,
    CapabilityRunRequest,
)
from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import (
    QueryRewriteResult,
    RAGRequest,
    RetrievalCandidate,
    RetrievalFilters,
)
from runtime.rag_runtime import (
    QueryRewriteRun,
    RAGRuntime,
)
from runtime.run_trace import (
    TraceDuplicateEventError,
    TraceRecorder,
)


_RUNTIME: RAGRuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def get_runtime() -> RAGRuntime:
    global _RUNTIME

    if _RUNTIME is None:
        with _RUNTIME_LOCK:
            if _RUNTIME is None:
                _RUNTIME = RAGRuntime()

    return _RUNTIME


def _filters_from_input(
    raw: Any,
) -> RetrievalFilters:
    if isinstance(raw, RetrievalFilters):
        return raw

    if not raw:
        return RetrievalFilters()

    if not isinstance(raw, dict):
        raise ValueError(
            "filters must be an object"
        )

    return RetrievalFilters.from_dict(raw)


def _candidate_summary(
    candidate: RetrievalCandidate,
) -> dict[str, Any]:
    return {
        "chunk_id": candidate.chunk_id,
        "source": candidate.source,
        "page": candidate.page,
        "vector_rank": candidate.vector_rank,
        "vector_score": candidate.vector_score,
        "bm25_rank": candidate.bm25_rank,
        "bm25_score": candidate.bm25_score,
        "rrf_rank": candidate.rrf_rank,
        "rrf_score": candidate.rrf_score,
        "rerank_rank": candidate.rerank_rank,
        "rerank_score": candidate.rerank_score,
    }


def _record_runtime_trace(
    recorder: TraceRecorder,
    trace,
) -> None:
    for trace_event in trace:
        try:
            recorder.append(
                CapabilityEvent.from_trace_event(
                    trace_event
                )
            )
        except TraceDuplicateEventError:
            continue


def _build_request(
    payload: CapabilityRunRequest,
    *,
    question: str,
    allow_rerank: bool,
) -> RAGRequest:
    return RAGRequest(
        question=question,
        thread_id=payload.thread_id,
        run_id=payload.run_id,
        filters=_filters_from_input(
            payload.input.get("filters")
        ),
        allow_rerank=allow_rerank,
    )


def _prepare_request(
    payload: CapabilityRunRequest,
    request: RAGRequest,
) -> QueryRewriteRun:
    semantic_query = str(
        payload.input.get(
            "semantic_query",
            "",
        )
    ).strip()

    keyword_query = str(
        payload.input.get(
            "keyword_query",
            "",
        )
    ).strip()

    if not semantic_query and not keyword_query:
        return get_runtime().prepare(request)

    run_id = (
        request.run_id
        or f"cap-{uuid4().hex}"
    )
    request = replace(
        request,
        run_id=run_id,
    )

    semantic_query = (
        semantic_query
        or request.question
    )
    keyword_query = (
        keyword_query
        or request.question
    )

    rewrite = QueryRewriteResult(
        original_query=request.question,
        normalized_query=request.question,
        semantic_query=semantic_query,
        keyword_query=keyword_query,
        inferred_filters=request.filters,
        version_policy="latest",
        reason="provided by capability input",
        raw_model_output="",
        model_name="provided",
    )

    return QueryRewriteRun(
        request=request,
        rewrite=rewrite,
        trace=(),
    )


def retrieval_hybrid_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    question = str(
        payload.input.get(
            "question",
            "",
        )
    ).strip()

    if not question:
        raise ValueError(
            "input.question is required"
        )

    runtime = get_runtime()
    request = _build_request(
        payload,
        question=question,
        allow_rerank=False,
    )
    prepared = _prepare_request(
        payload,
        request,
    )
    retrieved = runtime.retrieve(
        prepared,
        candidate_k=int(
            payload.input.get(
                "candidate_k",
                20,
            )
        ),
    )

    _record_runtime_trace(
        recorder,
        retrieved.trace,
    )

    return {
        "question": question,
        "retrieval": retrieved.retrieval.to_dict(),
        "vector_count": len(
            retrieved.retrieval.vector_candidates
        ),
        "bm25_count": len(
            retrieved.retrieval.bm25_candidates
        ),
        "fused_count": len(
            retrieved.retrieval.fused_candidates
        ),
    }


def rerank_comparison_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    question = str(
        payload.input.get(
            "question",
            "",
        )
    ).strip()

    if not question:
        raise ValueError(
            "input.question is required"
        )

    runtime = get_runtime()
    request = _build_request(
        payload,
        question=question,
        allow_rerank=True,
    )
    prepared = _prepare_request(
        payload,
        request,
    )
    retrieved = runtime.retrieve(
        prepared,
        candidate_k=int(
            payload.input.get(
                "candidate_k",
                10,
            )
        ),
    )

    _record_runtime_trace(
        recorder,
        retrieved.trace,
    )

    before = [
        _candidate_summary(item)
        for item in (
            retrieved.retrieval.fused_candidates
        )
    ]
    after = [
        _candidate_summary(item)
        for item in (
            retrieved.retrieval.reranked_candidates
        )
    ]

    rerank_event = next(
        (
            event
            for event in reversed(
                retrieved.trace
            )
            if event.operation == "rerank"
        ),
        None,
    )

    return {
        "question": question,
        "before": before,
        "after": after,
        "rerank_triggered": (
            rerank_event is not None
            and rerank_event.status.value
            != "skipped"
        ),
        "rerank_status": (
            rerank_event.status.value
            if rerank_event
            else ""
        ),
        "rerank_metadata": (
            rerank_event.metadata
            if rerank_event
            else {}
        ),
    }


def context_packing_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    question = str(
        payload.input.get(
            "question",
            "",
        )
    ).strip()

    if not question:
        raise ValueError(
            "input.question is required"
        )

    runtime = get_runtime()
    request = _build_request(
        payload,
        question=question,
        allow_rerank=bool(
            payload.input.get(
                "allow_rerank",
                False,
            )
        ),
    )
    prepared = _prepare_request(
        payload,
        request,
    )
    retrieved = runtime.retrieve(
        prepared,
        candidate_k=int(
            payload.input.get(
                "candidate_k",
                20,
            )
        ),
    )
    packaged = runtime.pack_context(
        retrieved,
        retrieval_budget=int(
            payload.input.get(
                "retrieval_budget",
                1800,
            )
        ),
        max_chunk_per_page=int(
            payload.input.get(
                "max_chunk_per_page",
                2,
            )
        ),
        max_chunk_per_parent=int(
            payload.input.get(
                "max_chunk_per_parent",
                2,
            )
        ),
    )

    _record_runtime_trace(
        recorder,
        packaged.trace,
    )

    context = packaged.context

    return {
        "context": context.to_dict(),
        "evidence_count": len(context.evidence),
        "citation_count": len(context.citations),
        "conflict_count": len(context.conflicts),
        "injection_count": len(
            context.injections
        ),
        "context_tokens": (
            context.context_tokens
        ),
        "source_diversity": (
            context.source_diversity
        ),
    }


def register_retrieval_capabilities(
    registry: CapabilityRegistry,
) -> None:
    if registry.has("retrieval_hybrid"):
        return

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="retrieval_hybrid",
                name="Hybrid Retrieval",
                description=(
                    "Run the real Vector, BM25 "
                    "and RRF retrieval pipeline."
                ),
                category="retrieval",
                tags=["vector", "bm25", "rrf"],
            ),
            handler=retrieval_hybrid_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="rerank_comparison",
                name="Rerank Comparison",
                description=(
                    "Compare RRF candidates "
                    "before and after reranking."
                ),
                category="retrieval",
                tags=["rerank", "cross_encoder"],
            ),
            handler=rerank_comparison_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="context_packing",
                name="Context Packing",
                description=(
                    "Build evidence, citation, "
                    "conflict and injection context."
                ),
                category="context",
                tags=[
                    "context",
                    "citation",
                    "conflict",
                ],
            ),
            handler=context_packing_handler,
        )
    )