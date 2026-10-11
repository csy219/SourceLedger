"""Smoke test for B09 real FastAPI /ask."""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime.api.S19_2_app import (
    create_app,
)


def main() -> int:
    app = create_app()

    with TestClient(app) as client:
        assert (
            app.state.ask_function
            .__module__
            == "runtime.ask_service"
        )

        payload = {
            "question": (
                "差旅报销制度中的"
                "住宿标准是什么？"
            ),
            "thread_id": "smoke-b09",
            "request_id": "smoke-b09-001",
        }

        first = client.post(
            "/ask",
            json=payload,
        )

        assert first.status_code == 200, (
            first.text
        )

        body = first.json()

        assert body["answer"].strip()
        assert body["citations"]
        assert body["total_tokens"] > 0
        assert body["latency_ms"] > 0
        assert body["status"] == "completed"
        assert body["run_id"]

        second = client.post(
            "/ask",
            json=payload,
        )

        assert second.status_code == 200
        second_body = second.json()

        assert (
            second_body["run_id"]
            == body["run_id"]
        )
        assert (
            second_body["replayed"]
            is True
        )

        print(
            "case=fastapi_ask passed=True "
            f"run_id={body['run_id']} "
            f"citations={len(body['citations'])} "
            f"context_tokens={body['context_tokens_est']} "
            f"total_tokens={body['total_tokens']} "
            f"latency_ms={body['latency_ms']}"
        )
        print(
            "answer_preview="
            f"{body['answer'][:80]}"
        )
        print(
            "citation_preview="
            f"{body['citations'][0]}"
        )

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())