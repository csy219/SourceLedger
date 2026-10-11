import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.S15_state_reference import (
    RunState,
    ToolCallRecord,
    ToolCallStatus,
)
from runtime.db.S16_3_run_repository import (
    RunStateRepository,
)
from runtime.db.S16_4_idempotency_repository import (
    IdempotencyRepository,
)
from runtime.db.S16_4_tool_call_repository import (
    ToolCallRepository,
)
from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)


def main() -> int:
    engine = create_db_engine()
    session_factory = create_session_factory(engine)

    run_repository = RunStateRepository(
        session_factory
    )
    tool_repository = ToolCallRepository(
        session_factory
    )
    idempotency_repository = (
        IdempotencyRepository(
            session_factory
        )
    )

    state = RunState.create(
        thread_id="thread-tool-repository-smoke",
        goal="测试 ToolCallRepository",
        max_steps=10,
    )
    run_repository.create(state)

    record = ToolCallRecord(
        tool_call_id="call-tool-1",
        tool_name="shell.run",
        arguments={"command": "pytest -q"},
    )

    first, first_created = (
        tool_repository.create_or_get(
            run_id=state.run_id,
            record=record,
        )
    )
    second, second_created = (
        tool_repository.create_or_get(
            run_id=state.run_id,
            record=record,
        )
    )

    print(f"first_created={first_created}")
    print(f"second_created={second_created}")

    running = tool_repository.mark_running(
        state.run_id,
        record.tool_call_id,
    )
    print(
        f"running_status={running.status.value} "
        f"attempt={running.attempt}"
    )

    succeeded = tool_repository.mark_succeeded(
        state.run_id,
        record.tool_call_id,
        {"exit_code": 0},
    )
    print(
        f"succeeded_status={succeeded.status.value}"
    )

    key = f"{state.run_id}:{record.tool_call_id}"

    _, first_key_created = (
        idempotency_repository.begin(
            key=key,
            run_id=state.run_id,
        )
    )
    _, second_key_created = (
        idempotency_repository.begin(
            key=key,
            run_id=state.run_id,
        )
    )
    idempotency_repository.complete(
        key=key,
        result={"exit_code": 0},
    )

    print(
        f"first_key_created={first_key_created}"
    )
    print(
        "second_key_created="
        f"{second_key_created}"
    )
    print(
        "tool_call_count="
        f"{len(tool_repository.list_by_run(state.run_id))}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())