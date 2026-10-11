"""Smoke test for C05 resilience capabilities."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from runtime.api.S19_2_app import create_app
from runtime.run_trace import (
    InMemoryTraceStore,
)


def run_capability(
    client: TestClient,
    capability_id: str,
    payload: dict,
    run_id: str,
) -> dict:
    response = client.post(
        f"/capabilities/{capability_id}/run",
        json={
            "run_id": run_id,
            "thread_id": "c05-smoke",
            "input": payload,
        },
    )

    assert response.status_code == 200, (
        f"{capability_id}: {response.text}"
    )

    body = response.json()
    trace = client.get(
        f"/runs/{run_id}/trace"
    )

    assert trace.status_code == 200
    assert trace.json()["event_count"] > 0

    return body["output"]


def main() -> int:
    trace_store = InMemoryTraceStore()
    app = create_app(
        trace_store=trace_store
    )

    with TestClient(app) as client:
        capabilities = client.get(
            "/capabilities"
        )

        assert capabilities.status_code == 200

        capability_ids = {
            item["capability_id"]
            for item in capabilities.json()
        }

        expected_ids = {
            "retry_backoff",
            "fallback_chain",
            "circuit_breaker",
            "rate_limit",
            "distributed_lock",
            "idempotency",
            "checkpoint_recovery",
        }

        assert expected_ids.issubset(
            capability_ids
        )

        retry = run_capability(
            client=client,
            capability_id="retry_backoff",
            run_id="c05-retry",
            payload={
                "succeed_on_attempt": 2,
                "max_attempts": 3,
                "base_delay_ms": 1,
                "max_delay_ms": 5,
            },
        )

        assert retry["status"] == "succeeded"
        assert retry["attempts"] == 2

        fallback = run_capability(
            client=client,
            capability_id="fallback_chain",
            run_id="c05-fallback",
            payload={
                "fallback_success": (
                    "bm25_only"
                ),
            },
        )

        assert fallback["status"] == "succeeded"
        assert fallback["source"] == "bm25_only"

        breaker = run_capability(
            client=client,
            capability_id="circuit_breaker",
            run_id="c05-breaker",
            payload={
                "failure_threshold": 2,
                "recovery_timeout_ms": 20,
            },
        )

        assert breaker["open_state"] == "open"
        assert (
            breaker["open_error"]
            == "CircuitOpenError"
        )
        assert (
            breaker["recovered_state"]
            == "closed"
        )

        rate_limit = run_capability(
            client=client,
            capability_id="rate_limit",
            run_id="c05-rate-limit",
            payload={
                "limit": 2,
                "window_seconds": 60,
                "request_count": 3,
            },
        )

        assert rate_limit["local_results"] == [
            True,
            True,
            False,
        ]
        assert rate_limit["redis_results"] == [
            True,
            True,
            False,
        ]

        lock = run_capability(
            client=client,
            capability_id="distributed_lock",
            run_id="c05-lock",
            payload={
                "ttl_ms": 500,
            },
        )

        assert lock["first_acquired"] is True
        assert (
            lock[
                "second_acquired_while_held"
            ]
            is False
        )
        assert (
            lock[
                "second_acquired_after_release"
            ]
            is True
        )

        idempotency = run_capability(
            client=client,
            capability_id="idempotency",
            run_id="c05-idempotency",
            payload={
                "key": (
                    "c05:"
                    + uuid.uuid4().hex
                ),
            },
        )

        assert (
            idempotency["first_replayed"]
            is False
        )
        assert (
            idempotency["second_replayed"]
            is True
        )
        assert idempotency["call_count"] == 1

        checkpoint = run_capability(
            client=client,
            capability_id=(
                "checkpoint_recovery"
            ),
            run_id=(
                "c05-checkpoint-"
                + uuid.uuid4().hex
            ),
            payload={},
        )

        assert checkpoint["status"] == "succeeded"
        assert checkpoint["versions"]
        assert (
            checkpoint["recovered_node"]
            == "recovered"
        )

        print(
            "case=retry_backoff passed=True "
            f"attempts={retry['attempts']}"
        )
        print(
            "case=fallback_chain passed=True "
            f"source={fallback['source']}"
        )
        print(
            "case=circuit_breaker passed=True "
            f"open={breaker['open_state']} "
            f"recovered={breaker['recovered_state']}"
        )
        print(
            "case=rate_limit passed=True "
            f"local={rate_limit['local_results']} "
            f"redis={rate_limit['redis_results']}"
        )
        print(
            "case=distributed_lock passed=True"
        )
        print(
            "case=idempotency passed=True "
            f"calls={idempotency['call_count']}"
        )
        print(
            "case=checkpoint_recovery "
            "passed=True "
            f"versions={checkpoint['versions']}"
        )

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())