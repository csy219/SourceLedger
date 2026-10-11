"""Smoke test for B03 parallel Vector and BM25 retrieval."""

from __future__ import annotations

from dotenv import load_dotenv

from runtime.B02_query_rewriter import (
    QueryRewriter,
)
from runtime.rag_contracts import RAGRequest
from runtime.rag_runtime import RAGRuntime


load_dotenv()


def main() -> int:
    request = RAGRequest(
        question=(
            "差旅报销制度中的"
            "住宿标准是什么？"
        ),
        thread_id="smoke-b03",
    )

    runtime = RAGRuntime(
        rewriter=QueryRewriter()
    )

    prepared = runtime.prepare(request)
    result = runtime.retrieve(
        prepared,
        candidate_k=10,
    )

    vector_count = len(
        result.retrieval.vector_candidates
    )
    bm25_count = len(
        result.retrieval.bm25_candidates
    )

    assert vector_count > 0
    assert bm25_count > 0
    assert len(result.trace) >= 5

    print(
        "case=parallel_retrieval passed=True "
        f"vector={vector_count} "
        f"bm25={bm25_count} "
        f"latency_ms={result.retrieval.latency_ms}"
    )

    first_vector = (
        result.retrieval
        .vector_candidates[0]
    )
    first_bm25 = (
        result.retrieval
        .bm25_candidates[0]
    )

    print(
        "vector_top1="
        f"{first_vector.source}:"
        f"{first_vector.page}"
    )
    print(
        "bm25_top1="
        f"{first_bm25.source}:"
        f"{first_bm25.page}"
    )

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())