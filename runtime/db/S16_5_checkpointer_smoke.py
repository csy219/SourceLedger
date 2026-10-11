import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.S15_state_reference import (
    RunState,
    RunStatus,
    ToolCallRecord,
    ToolCallStatus,
)
from runtime.db.S16_3_run_repository import (
    RunStateRepository,
)
from runtime.db.checkpointer import (
    DatabaseCheckpointer,
)
from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)


def main() -> int:
    engine = create_db_engine()
    session_factory = create_session_factory(
        engine
    )

    run_repository = RunStateRepository(
        session_factory
    )
    checkpointer = DatabaseCheckpointer(
        session_factory
    )

    state = RunState.create(
        thread_id="thread-checkpointer-smoke",
        goal="测试数据库 Checkpointer",
        max_steps=10,
    )
    run_repository.create(state)

    first = checkpointer.save(
        state,
        node="start",
    )

    state.status = RunStatus.RUNNING
    state.current_node = "call_model"
    state.step_count = 1
    state.context.messages.append(
        {
            "role": "user",
            "content": "检查仓库",
        }
    )

    record = ToolCallRecord(
        tool_call_id="call-checkpoint-1",
        tool_name="shell.run",
        arguments={"command": "pytest -q"},
    )
    record.mark_running()
    record.mark_succeeded(
        {"exit_code": 0}
    )
    state.tool_calls[
        record.tool_call_id
    ] = record

    second = checkpointer.save(
        state,
        node="after_tool",
    )

    loaded = checkpointer.load_latest(
        state.run_id
    )
    if loaded is None:
        raise RuntimeError("恢复失败")

    versions = checkpointer.list_versions(
        state.run_id
    )

    print(
        f"first_version={first.version}"
    )
    print(
        f"second_version={second.version}"
    )
    print(f"versions={versions}")
    print(
        f"loaded_status={loaded.status.value}"
    )
    print(
        f"loaded_node={loaded.current_node}"
    )
    print(
        f"loaded_step_count={loaded.step_count}"
    )
    print(
        "loaded_tool_status="
        f"{loaded.tool_calls['call-checkpoint-1'].status.value}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())