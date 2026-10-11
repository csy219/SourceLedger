"""Smoke test for C02 RunTrace and stores."""

from __future__ import annotations

from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import TraceStatus
from runtime.run_trace import (
    DatabaseTraceStore,
    InMemoryTraceStore,
    RunTrace,
    TraceCapacityError,
    TraceDuplicateEventError,
    TraceRecorder,
)


def make_event(
    event_id: str,
    run_id: str,
    timestamp: str,
    operation: str,
) -> CapabilityEvent:
    return CapabilityEvent(
        event_id=event_id,
        run_id=run_id,
        timestamp=timestamp,
        stage="retrieval",
        operation=operation,
        status=TraceStatus.SUCCEEDED,
        attempt=1,
        action="test",
        duration_ms=1.0,
        metadata={
            "nested": {
                "value": event_id,
            },
        },
    )


def test_memory_order_and_multi_run() -> None:
    store = InMemoryTraceStore()

    store.append_event(
        make_event(
            "event-2",
            "run-a",
            "2026-10-10T02:00:02+00:00",
            "bm25_search",
        )
    )
    store.append_event(
        make_event(
            "event-1",
            "run-a",
            "2026-10-10T02:00:01+00:00",
            "vector_search",
        )
    )
    store.append_event(
        make_event(
            "event-3",
            "run-b",
            "2026-10-10T02:00:03+00:00",
            "rrf_fusion",
        )
    )

    trace = store.get_run("run-a")

    assert [
        event.event_id
        for event in trace.events
    ] == [
        "event-1",
        "event-2",
    ]
    assert trace.event_count == 2
    assert trace.last_event is not None
    assert (
        trace.last_event.event_id
        == "event-2"
    )
    assert store.list_runs() == (
        "run-a",
        "run-b",
    )

    print(
        "case=memory_order_and_multi_run "
        "passed=True"
    )


def test_json_roundtrip() -> None:
    store = InMemoryTraceStore()

    store.append_event(
        make_event(
            "event-1",
            "run-json",
            "2026-10-10T02:00:01+00:00",
            "vector_search",
        )
    )

    trace = store.get_run("run-json")
    restored = RunTrace.from_json(
        trace.to_json()
    )

    assert restored == trace
    assert (
        restored.events[0]
        .metadata["nested"]["value"]
        == "event-1"
    )

    print(
        "case=json_roundtrip passed=True"
    )


def test_duplicate_detection() -> None:
    store = InMemoryTraceStore()

    event = make_event(
        "duplicate-1",
        "run-duplicate",
        "2026-10-10T02:00:01+00:00",
        "vector_search",
    )

    store.append_event(event)

    try:
        store.append_event(event)
    except TraceDuplicateEventError:
        pass
    else:
        raise AssertionError(
            "duplicate event_id was accepted"
        )

    print(
        "case=duplicate_detection "
        "passed=True"
    )


def test_capacity_limit() -> None:
    store = InMemoryTraceStore(
        max_events_per_run=2
    )

    store.append_event(
        make_event(
            "event-1",
            "run-capacity",
            "2026-10-10T02:00:01+00:00",
            "vector_search",
        )
    )
    store.append_event(
        make_event(
            "event-2",
            "run-capacity",
            "2026-10-10T02:00:02+00:00",
            "bm25_search",
        )
    )

    try:
        store.append_event(
            make_event(
                "event-3",
                "run-capacity",
                "2026-10-10T02:00:03+00:00",
                "rrf_fusion",
            )
        )
    except TraceCapacityError:
        pass
    else:
        raise AssertionError(
            "capacity limit was not enforced"
        )

    print(
        "case=capacity_limit passed=True"
    )


class FailingRepository:
    def append_event(self, event):
        raise RuntimeError("db unavailable")

    def get_events(self, run_id):
        raise RuntimeError("db unavailable")

    def list_run_ids(self):
        raise RuntimeError("db unavailable")

    def clear(self):
        raise RuntimeError("db unavailable")


def test_database_fallback() -> None:
    fallback = InMemoryTraceStore()

    store = DatabaseTraceStore(
        repository=FailingRepository(),
        fallback=fallback,
    )

    event = make_event(
        "event-1",
        "run-fallback",
        "2026-10-10T02:00:01+00:00",
        "vector_search",
    )

    store.append_event(event)
    trace = store.get_run("run-fallback")

    assert trace.event_count == 1
    assert store.list_runs() == (
        "run-fallback",
    )

    print(
        "case=database_fallback passed=True"
    )


def test_recorder_and_clear() -> None:
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)

    recorder.append(
        make_event(
            "event-1",
            "run-recorder",
            "2026-10-10T02:00:01+00:00",
            "vector_search",
        )
    )
    recorder.append_trace_events(
        (
            make_event(
                "event-2",
                "run-recorder",
                "2026-10-10T02:00:02+00:00",
                "bm25_search",
            ),
        )
    )

    trace = store.get_run("run-recorder")
    assert trace.event_count == 2

    store.clear()
    assert store.list_runs() == ()

    print(
        "case=recorder_and_clear passed=True"
    )


def main() -> int:
    test_memory_order_and_multi_run()
    test_json_roundtrip()
    test_duplicate_detection()
    test_capacity_limit()
    test_database_fallback()
    test_recorder_and_clear()

    print("all_passed=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())