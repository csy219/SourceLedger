import json
import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.security.S18_5_tool_failure_guard import (
    ToolFailureGuard,
)


def main() -> int:
    guard = ToolFailureGuard()

    dangerous = guard.execute(
        command="rm -rf /",
        func=lambda: {
            "exit_code": 0,
        },
    )

    nonzero = guard.execute(
        command="pytest -q",
        func=lambda: {
            "exit_code": 1,
            "stdout": "1 failed",
            "stderr": "AssertionError",
        },
    )

    timeout = guard.execute(
        command="pytest -q",
        func=lambda: (
            (_ for _ in ()).throw(
                TimeoutError("simulated")
            )
        ),
        side_effect_committed=False,
    )

    side_effect_timeout = guard.execute(
        command="git push",
        func=lambda: (
            (_ for _ in ()).throw(
                TimeoutError("network timeout")
            )
        ),
        side_effect_committed=True,
    )

    permission_denied = guard.execute(
        command="docker ps",
        func=lambda: (
            (_ for _ in ()).throw(
                PermissionError("denied")
            )
        ),
    )

    passed = (
        dangerous.status.value == "rejected"
        and not dangerous.executed
        and nonzero.status.value == "failed"
        and nonzero.exit_code == 1
        and timeout.status.value == "timed_out"
        and timeout.retryable
        and side_effect_timeout.status.value
        == "timed_out"
        and not side_effect_timeout.retryable
        and side_effect_timeout.manual_check_required
        and permission_denied.status.value
        == "rejected"
    )

    output = {
        "dangerous_command": {
            "status": dangerous.status.value,
            "executed": dangerous.executed,
            "reason": dangerous.reason,
        },
        "nonzero_exit": {
            "status": nonzero.status.value,
            "exit_code": nonzero.exit_code,
            "stderr": nonzero.stderr,
        },
        "timeout": {
            "status": timeout.status.value,
            "retryable": timeout.retryable,
            "manual_check_required": (
                timeout.manual_check_required
            ),
        },
        "side_effect_timeout": {
            "status": (
                side_effect_timeout.status.value
            ),
            "retryable": (
                side_effect_timeout.retryable
            ),
            "manual_check_required": (
                side_effect_timeout
                .manual_check_required
            ),
        },
        "permission_denied": {
            "status": (
                permission_denied.status.value
            ),
            "reason": permission_denied.reason,
        },
        "passed": passed,
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not passed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())