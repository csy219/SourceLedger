import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCENARIOS = [
    {
        "name": "security_fixtures",
        "module": (
            "runtime.security."
            "S18_1_security_fixture_smoke"
        ),
        "required_text": [
            "attack_types",
            "defense_layers",
        ],
    },
    {
        "name": "prompt_injection",
        "module": (
            "runtime.security."
            "S18_2_injection_smoke"
        ),
        "required_text": [
            "SEC01_direct_injection",
            "SEC02_indirect_injection",
            '"passed": true',
        ],
    },
    {
        "name": "no_evidence",
        "module": (
            "runtime.security."
            "S18_3_no_evidence_smoke"
        ),
        "required_text": [
            "no_retrieval_results",
            "score_below_threshold",
            "evidence_found",
            '"passed": true',
        ],
    },
    {
        "name": "context_integrity",
        "module": (
            "runtime.security."
            "S18_4_context_integrity_smoke"
        ),
        "required_text": [
            "context_contains_warning",
            "both_sources_present",
            "invalid_ids",
            '"all_passed": true',
        ],
    },
    {
        "name": "tool_failure",
        "module": (
            "runtime.security."
            "S18_5_tool_failure_smoke"
        ),
        "required_text": [
            "dangerous_command",
            "nonzero_exit",
            "side_effect_timeout",
            "permission_denied",
            '"passed": true',
        ],
    },
]


def run_scenario(
    scenario: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            scenario["module"],
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )

    elapsed_ms = (
        time.perf_counter() - started
    ) * 1000

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    combined_output = stdout + stderr

    missing_tokens = [
        token
        for token in scenario["required_text"]
        if token not in combined_output
    ]

    passed = (
        completed.returncode == 0
        and not missing_tokens
    )

    return {
        "name": scenario["name"],
        "module": scenario["module"],
        "return_code": completed.returncode,
        "elapsed_ms": round(elapsed_ms, 2),
        "missing_tokens": missing_tokens,
        "passed": passed,
        "stdout": stdout,
        "stderr": stderr,
    }

def main() -> int:
    project_root = (
        Path(__file__).resolve().parents[2]
    )
    report_path = (
        project_root
        / "evaluation"
        / "reports"
        / "S18_6_security_regression.json"
    )

    results = [
        run_scenario(
            scenario=scenario,
            project_root=project_root,
        )
        for scenario in SCENARIOS
    ]

    summary = {
        "scenarios": len(results),
        "passed": sum(
            1
            for item in results
            if item["passed"]
        ),
        "failed": sum(
            1
            for item in results
            if not item["passed"]
        ),
        "all_passed": all(
            item["passed"]
            for item in results
        ),
    }

    report = {
        "summary": summary,
        "results": results,
    }

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("===== S18 Security Regression =====")
    for item in results:
        print(
            f"{item['name']} "
            f"passed={item['passed']} "
            f"return_code={item['return_code']} "
            f"elapsed_ms={item['elapsed_ms']}"
        )
        if item["missing_tokens"]:
            print(
                "missing_tokens="
                f"{item['missing_tokens']}"
            )

    print(
        f"all_passed={summary['all_passed']}"
    )
    print(
        f"report={report_path.resolve()}"
    )

    if not summary["all_passed"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())