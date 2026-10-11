"""Smoke test for B08 timeout, retry and fallback."""

from __future__ import annotations

from runtime.rag_contracts import (
    RetrievalCandidate,
    RetrievalFilters,
)
from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)
from runtime.resilience.operation_policy import (
    ModelPermanentError,
    ModelTransientError,
    execute_resilient,
)
from runtime.resilience.retrieval_policy import (
    ResilientRetriever,
)
from runtime.resilience.S17_3_fallback import (
    FallbackExhausted,
)


def test_first_attempt_success() -> None:
    calls = {"count": 0}

    def primary() -> str:
        calls["count"] += 1
        return "ok"

    result = execute_resilient(
        operation_name="test.success",
        primary=primary,
        timeout_policy=TimeoutPolicy(
            timeout_ms=1000
        ),
        retry_policy=RetryPolicy(
            max_attempts=3,
            base_delay_ms=1,
            max_delay_ms=5,
            jitter_ratio=0.0,
        ),
    )

    assert result.value == "ok"
    assert result.source == "test.success"
    assert result.attempts == 1
    assert calls["count"] == 1

    print(
        "case=first_attempt_success "
        "passed=True"
    )


def test_retry_then_success() -> None:
    calls = {"count": 0}

    def primary() -> str:
        calls["count"] += 1

        if calls["count"] < 3:
            raise ModelTransientError(
                "temporary failure"
            )

        return "recovered"

    result = execute_resilient(
        operation_name="test.retry",
        primary=primary,
        timeout_policy=TimeoutPolicy(
            timeout_ms=1000
        ),
        retry_policy=RetryPolicy(
            max_attempts=3,
            base_delay_ms=1,
            max_delay_ms=5,
            jitter_ratio=0.0,
        ),
    )

    assert result.value == "recovered"
    assert result.source == "test.retry"
    assert result.attempts == 3
    assert calls["count"] == 3

    print(
        "case=retry_then_success "
        "passed=True"
    )


def test_retry_exhausted_fallback() -> None:
    calls = {"count": 0}

    def primary() -> str:
        calls["count"] += 1
        raise ModelTransientError(
            "service unavailable"
        )

    def cached() -> str:
        return "cached-response"

    result = execute_resilient(
        operation_name="test.fallback",
        primary=primary,
        timeout_policy=TimeoutPolicy(
            timeout_ms=1000
        ),
        retry_policy=RetryPolicy(
            max_attempts=2,
            base_delay_ms=1,
            max_delay_ms=5,
            jitter_ratio=0.0,
        ),
        fallback_chain=(
            "cached_response",
        ),
        fallback_handlers={
            "cached_response": cached,
        },
    )

    assert result.value == "cached-response"
    assert result.source == "cached_response"
    assert calls["count"] == 2
    assert result.fallback_attempts

    print(
        "case=retry_exhausted_fallback "
        "passed=True"
    )


def test_permanent_error_not_retried() -> None:
    calls = {"count": 0}

    def primary() -> str:
        calls["count"] += 1
        raise ModelPermanentError(
            "invalid api key"
        )

    try:
        execute_resilient(
            operation_name="test.permanent",
            primary=primary,
            timeout_policy=TimeoutPolicy(
                timeout_ms=1000
            ),
            retry_policy=RetryPolicy(
                max_attempts=3,
                base_delay_ms=1,
                max_delay_ms=5,
                jitter_ratio=0.0,
            ),
        )
    except FallbackExhausted:
        pass
    else:
        raise AssertionError(
            "permanent error must fail"
        )

    assert calls["count"] == 1

    print(
        "case=permanent_error_not_retried "
        "passed=True"
    )


class FlakyRetriever:
    def __init__(self) -> None:
        self.calls = 0

    def search(
        self,
        query: str,
        filters: RetrievalFilters,
        top_k: int,
    ):
        self.calls += 1

        if self.calls == 1:
            return (
                [
                    RetrievalCandidate(
                        chunk_id="cached-1",
                        text="cached text",
                        source="doc.pdf",
                        page=1,
                    )
                ],
                1.0,
            )

        raise ModelTransientError(
            "retrieval unavailable"
        )


def test_cached_retrieval_fallback() -> None:
    retriever = FlakyRetriever()

    resilient = ResilientRetriever(
        retriever=retriever,
        operation_name="test.retrieval",
        timeout_policy=TimeoutPolicy(
            timeout_ms=1000
        ),
        retry_policy=RetryPolicy(
            max_attempts=1,
            base_delay_ms=1,
            max_delay_ms=2,
            jitter_ratio=0.0,
        ),
    )

    first = resilient.search(
        query="same query",
        filters=RetrievalFilters(),
        top_k=3,
    )

    second = resilient.search(
        query="same query",
        filters=RetrievalFilters(),
        top_k=3,
    )

    assert first.source == "test.retrieval"
    assert first.candidates

    assert (
        second.source
        == "cached_retrieval"
    )
    assert second.candidates

    print(
        "case=cached_retrieval_fallback "
        "passed=True"
    )


def main() -> int:
    test_first_attempt_success()
    test_retry_then_success()
    test_retry_exhausted_fallback()
    test_permanent_error_not_retried()
    test_cached_retrieval_fallback()

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())