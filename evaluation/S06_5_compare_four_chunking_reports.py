import argparse
import json
from pathlib import Path
from typing import Any


CORE_KEYS = [
    "retrieval_passed",
    "retrieval_accuracy",
    "hit_at_1",
    "hit_at_metric_k",
    "recall_at_metric_k",
    "mrr",
    "latency_ms_avg",
]

CONTEXT_KEYS = [
    "parent_occurrences_avg",
    "unique_parents_avg",
    "context_chars_avg",
    "context_chars_max",
    "context_tokens_est_avg",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对比四种分块与检索模式"
    )
    parser.add_argument(
        "--fixed",
        type=Path,
        default=Path(__file__).parent / "reports"
        / "fixed_chunk_baseline.json",
    )
    parser.add_argument(
        "--structure",
        type=Path,
        default=Path(__file__).parent / "reports"
        / "structure_chunk_baseline.json",
    )
    parser.add_argument(
        "--semantic",
        type=Path,
        default=Path(__file__).parent / "reports"
        / "semantic_chunk_baseline.json",
    )
    parser.add_argument(
        "--parent-child",
        type=Path,
        default=Path(__file__).parent / "reports"
        / "parent_child_chunk_baseline.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "reports"
        / "S06_5_four_way_comparison.json",
    )
    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_core_table(
    reports: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    table = {}

    for key in CORE_KEYS:
        values = {
            name: report["summary"].get(key)
            for name, report in reports.items()
        }
        values["parent_child_vs_fixed"] = (
            round(values["parent_child"] - values["fixed"], 4)
            if values["parent_child"] is not None
            and values["fixed"] is not None
            else None
        )
        values["parent_child_vs_structure"] = (
            round(
                values["parent_child"] - values["structure"],
                4,
            )
            if values["parent_child"] is not None
            and values["structure"] is not None
            else None
        )
        values["parent_child_vs_semantic"] = (
            round(
                values["parent_child"] - values["semantic"],
                4,
            )
            if values["parent_child"] is not None
            and values["semantic"] is not None
            else None
        )
        table[key] = values

    return table


def build_context_table(
    parent_child_report: dict[str, Any],
) -> dict[str, Any]:
    summary = parent_child_report["summary"]
    return {
        key: summary.get(key)
        for key in CONTEXT_KEYS
    }


def compare_cases(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    baseline_map = {row["id"]: row for row in baseline_rows}
    candidate_map = {row["id"]: row for row in candidate_rows}

    result = {
        "improved": [],
        "regressed": [],
        "both_failed": [],
    }

    for case_id in sorted(baseline_map):
        baseline = baseline_map[case_id]
        candidate = candidate_map[case_id]

        item = {
            "id": case_id,
            "category": baseline["category"],
            "baseline_ranks": baseline["ranks"],
            "candidate_ranks": candidate["ranks"],
        }

        if (
            not baseline["retrieval_ok"]
            and candidate["retrieval_ok"]
        ):
            result["improved"].append(item)
        elif (
            baseline["retrieval_ok"]
            and not candidate["retrieval_ok"]
        ):
            result["regressed"].append(item)
        elif not candidate["retrieval_ok"]:
            result["both_failed"].append(item)

    return result


def main() -> int:
    args = parse_args()

    reports = {
        "fixed": load_report(args.fixed),
        "structure": load_report(args.structure),
        "semantic": load_report(args.semantic),
        "parent_child": load_report(args.parent_child),
    }

    core_table = build_core_table(reports)
    context_table = build_context_table(reports["parent_child"])

    case_comparison = {
        "parent_child_vs_fixed": compare_cases(
            reports["fixed"]["rows"],
            reports["parent_child"]["rows"],
        ),
        "parent_child_vs_structure": compare_cases(
            reports["structure"]["rows"],
            reports["parent_child"]["rows"],
        ),
        "parent_child_vs_semantic": compare_cases(
            reports["semantic"]["rows"],
            reports["parent_child"]["rows"],
        ),
    }

    output = {
        "core_table": core_table,
        "context_table": context_table,
        "case_comparison": case_comparison,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== Four-way Comparison =====")
    for key, values in core_table.items():
        print(
            f"{key}: "
            f"fixed={values['fixed']} "
            f"structure={values['structure']} "
            f"semantic={values['semantic']} "
            f"parent_child={values['parent_child']} "
            f"pc-fixed={values['parent_child_vs_fixed']:+} "
            f"pc-semantic={values['parent_child_vs_semantic']:+}"
        )

    print("\ncontext:")
    for key, value in context_table.items():
        print(f"{key}: {value}")

    for name, comparison in case_comparison.items():
        print(f"\n{name}")
        for group in ("improved", "regressed", "both_failed"):
            ids = [item["id"] for item in comparison[group]]
            print(f"  {group}: {ids}")

    print(f"\nreport: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())