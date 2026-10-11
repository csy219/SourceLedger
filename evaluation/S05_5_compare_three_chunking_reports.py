import argparse
import json
from pathlib import Path
from typing import Any


SUMMARY_KEYS = [
    "retrieval_passed",
    "retrieval_accuracy",
    "hit_at_1",
    "hit_at_metric_k",
    "recall_at_metric_k",
    "mrr",
    "latency_ms_avg",
    "latency_ms_p50",
    "latency_ms_max",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对比 fixed、structure 和 semantic 三份报告"
    )

    parser.add_argument(
        "--fixed",
        type=Path,
        default=(
            Path(__file__).parent
            / "reports"
            / "fixed_chunk_baseline.json"
        ),
    )
    parser.add_argument(
        "--structure",
        type=Path,
        default=(
            Path(__file__).parent
            / "reports"
            / "structure_chunk_baseline.json"
        ),
    )
    parser.add_argument(
        "--semantic",
        type=Path,
        default=(
            Path(__file__).parent
            / "reports"
            / "semantic_chunk_baseline.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            Path(__file__).parent
            / "reports"
            / "S05_5_three_chunking_comparison.json"
        ),
    )

    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def build_summary_table(
    reports: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    table = {}

    for key in SUMMARY_KEYS:
        values = {
            name: report["summary"][key]
            for name, report in reports.items()
        }
        values["semantic_vs_fixed"] = round(
            values["semantic"] - values["fixed"],
            4,
        )
        values["semantic_vs_structure"] = round(
            values["semantic"] - values["structure"],
            4,
        )
        table[key] = values

    return table


def compare_cases(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    baseline_map = {row["id"]: row for row in baseline_rows}
    candidate_map = {row["id"]: row for row in candidate_rows}

    improved = []
    regressed = []
    both_failed = []

    for case_id in sorted(baseline_map):
        baseline = baseline_map[case_id]
        candidate = candidate_map[case_id]

        item = {
            "id": case_id,
            "category": baseline["category"],
            "baseline_ok": baseline["retrieval_ok"],
            "candidate_ok": candidate["retrieval_ok"],
            "baseline_ranks": baseline["ranks"],
            "candidate_ranks": candidate["ranks"],
        }

        if not baseline["retrieval_ok"] and candidate["retrieval_ok"]:
            improved.append(item)
        elif baseline["retrieval_ok"] and not candidate["retrieval_ok"]:
            regressed.append(item)
        elif not candidate["retrieval_ok"]:
            both_failed.append(item)

    return {
        "improved": improved,
        "regressed": regressed,
        "both_failed": both_failed,
    }


def main() -> int:
    args = parse_args()

    reports = {
        "fixed": load_report(args.fixed),
        "structure": load_report(args.structure),
        "semantic": load_report(args.semantic),
    }

    summary_table = build_summary_table(reports)
    semantic_vs_fixed = compare_cases(
        baseline_rows=reports["fixed"]["rows"],
        candidate_rows=reports["semantic"]["rows"],
    )
    semantic_vs_structure = compare_cases(
        baseline_rows=reports["structure"]["rows"],
        candidate_rows=reports["semantic"]["rows"],
    )

    result = {
        "reports": {
            name: str(path.resolve())
            for name, path in {
                "fixed": args.fixed,
                "structure": args.structure,
                "semantic": args.semantic,
            }.items()
        },
        "summary_table": summary_table,
        "semantic_vs_fixed": semantic_vs_fixed,
        "semantic_vs_structure": semantic_vs_structure,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== Three-way Chunking Comparison =====")
    for key, values in summary_table.items():
        print(
            f"{key}: "
            f"fixed={values['fixed']} "
            f"structure={values['structure']} "
            f"semantic={values['semantic']} "
            f"semantic-fixed={values['semantic_vs_fixed']:+} "
            f"semantic-structure={values['semantic_vs_structure']:+}"
        )

    for name, comparison in (
        ("semantic_vs_fixed", semantic_vs_fixed),
        ("semantic_vs_structure", semantic_vs_structure),
    ):
        print(f"\n{name}")
        for group in ("improved", "regressed", "both_failed"):
            ids = [item["id"] for item in comparison[group]]
            print(f"  {group}: {ids}")

    print(f"\nreport: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())