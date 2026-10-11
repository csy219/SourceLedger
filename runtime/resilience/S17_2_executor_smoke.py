import json
import sys
import time
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from runtime.resilience.S17_2_executor import (
    NonRetryableOperationError,
    RetryExhausted,
    execute_with_policy,
    run_with_timeout,
)
from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)


def main()->int:
    attempts={"count":0}

    def flaky()->str:
        attempts["count"]+=1
        if attempts["count"]<3:
            raise ConnectionError(
                "temperary connection error"
            )
        return "ok"

    success = execute_with_policy(
        operation_name="flaky",
        timeout_policy=TimeoutPolicy(
            timeout_ms=1000
        ),
        retry_policy=RetryPolicy(
            max_attempts=3,
            base_delay_ms=5,
            max_delay_ms=20,
            jitter_ratio=0.0,
        ),
        func=flaky,
    )

    timeout_error=""
    try:
        run_with_timeout(
            operation_name="slow",
            timeout_ms=20,
            func=lambda: time.sleep(0.1),
        )
    except TimeoutError as exc:
        timeout_error=type(exc).__name__

    retry_error = ""
    try:
        execute_with_policy(
            operation_name="always-timeout",
            timeout_policy=TimeoutPolicy(
                timeout_ms=20
            ),
            retry_policy=RetryPolicy(
                max_attempts=2,
                base_delay_ms=5,
                max_delay_ms=10,
                jitter_ratio=0.0,
            ),
            func=lambda: time.sleep(0.1),
        )
    except RetryExhausted as exc:
        retry_error = (
            f"{type(exc).__name__}:"
            f"{exc.attempts}"
        )

    non_retryable = ""
    try:
        execute_with_policy(
            operation_name="bad-request",
            timeout_policy=TimeoutPolicy(
                timeout_ms=1000
            ),
            retry_policy=RetryPolicy(
                max_attempts=3,
                base_delay_ms=5,
                max_delay_ms=10,
                jitter_ratio=0.0,
            ),
            func=lambda: (
                (_ for _ in ()).throw(
                    ValueError("invalid input")
                )
            ),
        )
    except NonRetryableOperationError as exc:
        non_retryable = type(exc).__name__

    output = {
        "success_value": success.value,
        "success_attempts": success.attempts,
        "success_elapsed_ms": success.elapsed_ms,
        "timeout_error": timeout_error,
        "retry_error": retry_error,
        "non_retryable_error": non_retryable,
    }
    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())