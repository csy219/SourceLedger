"""Smoke test for B04 RRF hybrid fusion."""

from __future__ import annotations

from dotenv import load_dotenv

from runtime.B02_query_rewriter import (
    QueryRewriter,
)
from runtime.rag_contracts import (
    RAGRequest,
    RetrievalMode,
)
from runtime.rag_runtime import RAGRuntime


load_dotenv()


def main() -> int:
    request = RAGRequest(
        question=(
            "差旅报销制度中的"
            "住宿标准是什么？"
        ),
        thread_id="smoke-b04",
    )

    runtime = RAGRuntime(
        rewriter=QueryRewriter()
    )

    prepared = runtime.prepare(request)

    result = runtime.retrieve(
        prepared,
        candidate_k=10,
    )

    fused = (
        result.retrieval
        .fused_candidates
    )

    assert fused
    assert (
        result.retrieval.mode
        is RetrievalMode.HYBRID_RRF
    )
    assert all(
        candidate.rrf_rank is not None
        for candidate in fused
    )
    assert all(
        candidate.rrf_score is not None
        for candidate in fused
    )

    scores = [
        candidate.rrf_score
        for candidate in fused
    ]

    assert scores == sorted(
        scores,
        reverse=True,
    )

    assert len(result.trace) >= 6

    top = fused[0]

    print(
        "case=rrf_fusion passed=True "
        f"fused={len(fused)} "
        f"rrf_latency_ms={result.retrieval.metadata.get('rrf_latency_ms')}"
    )
    print(
        "top1="
        f"{top.source}:{top.page} "
        f"vector_rank={top.vector_rank} "
        f"bm25_rank={top.bm25_rank} "
        f"rrf_score={top.rrf_score}"
    )
    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())