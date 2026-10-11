import argparse
import json
import os
from pathlib import Path

from runtime.db.checkpointer import (
    DatabaseCheckpointer,
)
from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    artifact = json.loads(
        args.artifact.read_text(
            encoding="utf-8"
        )
    )

    engine = create_db_engine()
    session_factory = create_session_factory(
        engine
    )
    checkpointer = DatabaseCheckpointer(
        session_factory
    )

    state = checkpointer.load_latest(
        artifact["run_id"]
    )

    if state is None:
        raise RuntimeError(
            "跨进程恢复失败：没有找到 Checkpoint"
        )

    actual = {
        "status": state.status.value,
        "node": state.current_node,
        "step_count": state.step_count,
        "tool_status": state.tool_calls[
            "call-recovery-1"
        ].status.value,
    }
    expected = {
        "status": artifact["expected_status"],
        "node": artifact["expected_node"],
        "step_count": artifact[
            "expected_step_count"
        ],
        "tool_status": artifact[
            "expected_tool_status"
        ],
    }

    print(f"reader_pid={os.getpid()}")
    print(f"run_id={state.run_id}")
    print(f"recovered={actual}")

    if actual != expected:
        raise AssertionError(
            f"恢复结果不一致 expected={expected} "
            f"actual={actual}"
        )

    print("recovery_ok=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())