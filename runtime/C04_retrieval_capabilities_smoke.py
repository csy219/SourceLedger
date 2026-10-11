"""Smoke test for C04 retrieval capabilities."""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime.api.S19_2_app import create_app
from runtime.run_trace import (
    InMemoryTraceStore,
)


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

        ids = {
            item["capability_id"]
            for item in capabilities.json()
        }

        assert {
            "retrieval_hybrid",
            "rerank_comparison",
            "context_packing",
        }.issubset(ids)

        base_request = {
            "thread_id": "c04-smoke",
            "input": {
                "question": (
                    "差旅报销制度中的"
                    "住宿标准是什么？"
                ),
                "semantic_query": (
                    "差旅报销制度中的"
                    "住宿标准是什么？"
                ),
                "keyword_query": (
                    "差旅 报销 制度 住宿 标准"
                ),
                "candidate_k": 5,
            },
        }

        retrieval = client.post(
            "/capabilities/retrieval_hybrid/run",
            json={
                **base_request,
                "run_id": "c04-hybrid",
            },
        )

        assert retrieval.status_code == 200, (
            retrieval.text
        )

        retrieval_body = retrieval.json()
        output = retrieval_body["output"]

        assert output["vector_count"] > 0
        assert output["bm25_count"] > 0
        assert output["fused_count"] > 0

        rerank = client.post(
            "/capabilities/rerank_comparison/run",
            json={
                **base_request,
                "run_id": "c04-rerank",
            },
        )

        assert rerank.status_code == 200, (
            rerank.text
        )

        rerank_output = rerank.json()["output"]

        assert rerank_output["before"]
        assert rerank_output["after"]
        assert (
            rerank_output[
                "rerank_triggered"
            ]
            is True
        )

        context = client.post(
            "/capabilities/context_packing/run",
            json={
                **base_request,
                "run_id": "c04-context",
            },
        )

        assert context.status_code == 200, (
            context.text
        )

        context_output = context.json()["output"]

        assert context_output[
            "evidence_count"
        ] > 0
        assert context_output[
            "citation_count"
        ] > 0
        assert context_output[
            "context_tokens"
        ] > 0

        trace = client.get(
            "/runs/c04-hybrid/trace"
        )
        assert trace.status_code == 200
        assert (
            trace.json()["event_count"]
            >= 4
        )

        print(
            "case=retrieval_hybrid passed=True "
            f"vector={output['vector_count']} "
            f"bm25={output['bm25_count']} "
            f"rrf={output['fused_count']}"
        )
        print(
            "case=rerank_comparison "
            "passed=True "
            f"backend="
            f"{rerank_output.get('rerank_metadata', {}).get('backend')}"
        )
        print(
            "case=context_packing passed=True "
            f"evidence={context_output['evidence_count']} "
            f"citations={context_output['citation_count']} "
            f"tokens={context_output['context_tokens']}"
        )

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())