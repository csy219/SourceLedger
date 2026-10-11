import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.security.S18_1_security_fixture_loader import (
    load_security_cases,
)


def main() -> int:
    path = (
        PROJECT_ROOT
        / "evaluation"
        / "security"
        / "S18_security_set.json"
    )
    cases = load_security_cases(path)

    counts = Counter(
        case.attack_type
        for case in cases
    )

    output = {
        "cases": len(cases),
        "attack_types": dict(
            sorted(counts.items())
        ),
        "defense_layers": sorted(
            {
                layer
                for case in cases
                for layer in case.defense_layer
            }
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