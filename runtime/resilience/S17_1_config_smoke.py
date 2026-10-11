import json
import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.resilience.config import (
    load_resilience_config,
)


def main() -> int:
    config_path = (
        PROJECT_ROOT
        / "configs"
        / "resilience.json"
    )
    config = load_resilience_config(
        config_path
    )

    output = {}

    for name, operation in (
        config.operations.items()
    ):
        output[name] = {
            "timeout_ms": (
                operation.timeout.timeout_ms
            ),
            "max_attempts": (
                operation.retry.max_attempts
            ),
            "fallback_chain": list(
                operation.fallback.chain
            ),
            "rate_limit_enabled": (
                operation.rate_limit.enabled
            ),
            "idempotency_enabled": (
                operation.idempotency.enabled
            ),
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