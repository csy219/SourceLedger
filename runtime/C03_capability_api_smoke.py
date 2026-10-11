"""Smoke test for C03 Capability API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime.api.capabilities import (
    CapabilityDefinition,
    CapabilityDescriptor,
    CapabilityRegistry,
)
from runtime.api.S19_2_app import create_app
from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import TraceStatus
from runtime.run_trace import (
    InMemoryTraceStore,
)


def build_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()

    def echo_handler(
        request,
        recorder,
    ):
        value = request.input.get(
            "value",
            "",
        )

        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{request.run_id}:"
                    "echo:inside"
                ),
                run_id=(
                    request.run_id
                    or "missing-run-id"
                ),
                stage="capability",
                operation="echo",
                status=TraceStatus.SUCCEEDED,
                action="echo_input",
                metadata={
                    "value_length": len(
                        str(value)
                    ),
                },
            )
        )

        return {
            "echo": value,
            "thread_id": (
                request.thread_id
            ),
        }

    def fail_handler(
        request,
        recorder,
    ):
        raise RuntimeError(
            "forced capability failure"
        )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="echo",
                name="Echo",
                description=(
                    "Return the supplied input value."
                ),
                category="test",
                tags=[
                    "smoke",
                    "test",
                ],
            ),
            handler=echo_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="fail",
                name="Failure",
                description=(
                    "Always raise an error."
                ),
                category="test",
                tags=["smoke"],
            ),
            handler=fail_handler,
        )
    )

    return registry


def main() -> int:
    registry = build_registry()
    trace_store = InMemoryTraceStore()

    app = create_app(
        trace_store=trace_store,
        capabilities=registry,
    )

    with TestClient(app) as client:
        capabilities = client.get(
            "/capabilities"
        )

        assert capabilities.status_code == 200

        descriptors = capabilities.json()
        capability_ids = {
            item["capability_id"]
            for item in descriptors
        }

        assert capability_ids == {
            "echo",
            "fail",
        }

        run = client.post(
            "/capabilities/echo/run",
            json={
                "run_id": "c03-echo-run",
                "thread_id": "c03-thread",
                "input": {
                    "value": "hello",
                },
            },
        )

        assert run.status_code == 200, run.text

        run_body = run.json()

        assert (
            run_body["capability_id"]
            == "echo"
        )

        assert (
            run_body["output"]["echo"]
            == "hello"
        )

        assert run_body["event_count"] >= 3

        trace = client.get(
            "/runs/c03-echo-run/trace"
        )

        assert trace.status_code == 200

        trace_body = trace.json()
        operations = [
            event["operation"]
            for event in trace_body["events"]
        ]

        assert trace_body["event_count"] >= 3
        assert "echo" in operations
        assert (
            trace_body["events"][0]["status"]
            == "started"
        )
        assert (
            trace_body["events"][-1]["status"]
            == "succeeded"
        )

        unknown = client.post(
            "/capabilities/unknown/run",
            json={
                "input": {},
            },
        )

        assert unknown.status_code == 404

        missing_trace = client.get(
            "/runs/not-found/trace"
        )

        assert (
            missing_trace.status_code
            == 404
        )

        failed = client.post(
            "/capabilities/fail/run",
            json={
                "run_id": "c03-fail-run",
                "input": {},
            },
        )

        assert failed.status_code == 500

        failed_trace = client.get(
            "/runs/c03-fail-run/trace"
        )

        assert (
            failed_trace.status_code
            == 200
        )

        failed_events = (
            failed_trace.json()["events"]
        )

        assert len(failed_events) == 2
        assert (
            failed_events[-1]["status"]
            == "failed"
        )

        print(
            "case=list_capabilities passed=True "
            f"count={len(descriptors)}"
        )
        print(
            "case=run_capability passed=True "
            f"events={run_body['event_count']}"
        )
        print(
            "case=get_run_trace passed=True "
            f"events={trace_body['event_count']}"
        )
        print(
            "case=unknown_capability passed=True"
        )
        print(
            "case=missing_trace passed=True"
        )
        print(
            "case=failed_capability passed=True"
        )

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())