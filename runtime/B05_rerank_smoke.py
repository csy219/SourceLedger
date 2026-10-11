"""Smoke test for B05 conditional reranking."""

from __future__ import annotations

from dotenv import load_dotenv

from runtime.B02_query_rewriter import (
    QueryRewriter,
)
from runtime.rag_contracts import (
    RAGRequest,
    RetrievalCandidate,
    RetrievalMode,
    TraceStatus,
)
from runtime.rag_runtime import RAGRuntime
from runtime.retrieval.reranker import (
    Reranker,
    RerankerConfig,
    should_rerank,
)


load_dotenv()


def test_skip_decision() -> None:
    candidates = (
        RetrievalCandidate(
            chunk_id="a",
            text="A",
            source="doc.pdf",
            page=1,
            rrf_rank=1,
            rrf_score=0.03,
        ),
        RetrievalCandidate(
            chunk_id="b",
            text="B",
            source="doc.pdf",
            page=2,
            rrf_rank=2,
            rrf_score=0.01,
        ),
    )

    config = RerankerConfig(
        candidate_threshold=100,
        score_margin_threshold=0.0,
    )

    triggered, reason = should_rerank(
        candidates=candidates,
        allow_rerank=False,
        query_ambiguous=False,
        config=config,
    )

    assert triggered is False
    assert reason == "conditions_not_met"

    print(
        "case=rerank_skip_decision "
        "passed=True"
    )


def test_forced_rerank() -> None:
    request = RAGRequest(
        question=(
            "差旅报销制度中的"
            "住宿标准是什么？"
        ),
        thread_id="smoke-b05",
        allow_rerank=True,
    )

    runtime = RAGRuntime(
        rewriter=QueryRewriter(),
        reranker=Reranker(
            config=RerankerConfig(
                candidate_threshold=0,
                score_margin_threshold=0.0,
            )
        ),
    )

    prepared = runtime.prepare(request)

    result = runtime.retrieve(
        prepared,
        candidate_k=5,
    )

    assert (
        result.retrieval.mode
        is RetrievalMode.HYBRID_RERANK
    )
    assert (
        result.retrieval
        .reranked_candidates
    )

    assert (
        result.trace[-1].status
        is not TraceStatus.SKIPPED
    )

    top = (
        result.retrieval
        .reranked_candidates[0]
    )

    print(
        "case=forced_rerank passed=True "
        f"reranked="
        f"{len(result.retrieval.reranked_candidates)} "
        f"backend="
        f"{result.trace[-1].metadata.get('backend')} "
        f"load_ms="
        f"{result.trace[-1].metadata.get('load_ms')} "
        f"latency_ms="
        f"{result.trace[-1].duration_ms}"
    )
    print(
        f"top1={top.source}:{top.page} "
        f"rerank_rank={top.rerank_rank} "
        f"rerank_score={top.rerank_score}"
    )


def main() -> int:
    test_skip_decision()
    test_forced_rerank()

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())