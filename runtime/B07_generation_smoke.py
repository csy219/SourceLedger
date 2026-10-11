"""Smoke test for B07 real answer generation."""

from __future__ import annotations

from dotenv import load_dotenv

from runtime.B02_query_rewriter import (
    QueryRewriter,
)
from runtime.generation import (
    AnswerGenerator,
)
from runtime.rag_contracts import (
    ContextPack,
    FailureCode,
    RAGRequest,
    RAGStatus,
)
from runtime.rag_runtime import RAGRuntime


load_dotenv()


def test_invalid_citation_cleanup() -> None:
    (
        cleaned,
        invalid,
    ) = (
        AnswerGenerator
        ._clean_invalid_citations(
            answer=(
                "住宿标准为每晚 500 元 "
                "[C1] [C99]。"
            ),
            allowed_ids={"C1"},
        )
    )

    assert invalid == ("C99",)
    assert "[C99]" not in cleaned
    assert "[C1]" in cleaned

    print(
        "case=invalid_citation_cleanup "
        "passed=True"
    )


def test_no_evidence_refusal() -> None:
    generator = AnswerGenerator()

    result = generator.generate(
        question="公司年假有多少天？",
        context=ContextPack(),
    )

    assert (
        result.answer.status
        is RAGStatus.NO_EVIDENCE
    )
    assert result.answer.failure is not None
    assert (
        result.answer.failure.code
        is FailureCode.NO_EVIDENCE
    )

    print(
        "case=no_evidence_refusal "
        "passed=True"
    )


def test_real_generation() -> None:
    request = RAGRequest(
        question=(
            "差旅报销制度中的"
            "住宿标准是什么？"
        ),
        thread_id="smoke-b07",
    )

    runtime = RAGRuntime(
        rewriter=QueryRewriter(),
        generator=AnswerGenerator(),
    )

    prepared = runtime.prepare(request)

    retrieved = runtime.retrieve(
        prepared,
        candidate_k=10,
    )

    packaged = runtime.pack_context(
        retrieved,
        retrieval_budget=1800,
    )

    generated = runtime.generate(
        packaged
    )

    answer = generated.answer

    assert (
        answer.status
        is RAGStatus.SUCCEEDED
    )
    assert answer.answer.strip()
    assert answer.citations
    assert answer.usage.total_tokens > 0
    assert len(generated.trace) >= 8

    generation_event = (
        generated.trace[-1]
    )

    assert (
        generation_event.stage
        == "generation"
    )
    assert (
        generation_event.metadata[
            "invalid_citation_ids"
        ]
        == []
    )

    print(
        "case=real_generation passed=True "
        f"citations={len(answer.citations)} "
        f"tokens={answer.usage.total_tokens} "
        f"latency_ms={answer.latency_ms}"
    )
    print(
        "answer_preview="
        f"{answer.answer[:80]}"
    )


def main() -> int:
    test_invalid_citation_cleanup()
    test_no_evidence_refusal()
    test_real_generation()

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())