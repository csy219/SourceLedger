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
        description="对比 fixed 与 structure 检索报告"
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
        "--output",
        type=Path,
        default=(
            Path(__file__).parent
            / "reports"
            / "S04_5_chunking_comparison.json"
        ),
    )

    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def build_summary_delta(
    fixed_summary: dict[str, Any],
    structure_summary: dict[str, Any],
) -> dict[str, dict[str, float | int]]:
    comparison = {}

    for key in SUMMARY_KEYS:
        fixed_value = fixed_summary[key]
        structure_value = structure_summary[key]

        comparison[key] = {
            "fixed": fixed_value,
            "structure": structure_value,
            "delta": round(structure_value - fixed_value, 4),
        }

    return comparison


def compare_rows(
    fixed_rows: list[dict[str, Any]],
    structure_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    fixed_map = {row["id"]: row for row in fixed_rows}
    structure_map = {row["id"]: row for row in structure_rows}

    if fixed_map.keys() != structure_map.keys():
        raise ValueError("两份报告的用例 ID 不一致")

    improved = []
    regressed = []
    both_passed = []
    both_failed = []

    for case_id in sorted(fixed_map):
        fixed_row = fixed_map[case_id]
        structure_row = structure_map[case_id]

        item = {
            "id": case_id,
            "category": fixed_row["category"],
            "fixed_ok": fixed_row["retrieval_ok"],
            "structure_ok": structure_row["retrieval_ok"],
            "fixed_ranks": fixed_row["ranks"],
            "structure_ranks": structure_row["ranks"],
        }

        if (
            not fixed_row["retrieval_ok"]
            and structure_row["retrieval_ok"]
        ):
            improved.append(item)
        elif (
            fixed_row["retrieval_ok"]
            and not structure_row["retrieval_ok"]
        ):
            regressed.append(item)
        elif structure_row["retrieval_ok"]:
            both_passed.append(item)
        else:
            both_failed.append(item)

    return {
        "improved": improved,
        "regressed": regressed,
        "both_passed": both_passed,
        "both_failed": both_failed,
    }


def main() -> int:
    args = parse_args()

    fixed_report = load_report(args.fixed)
    structure_report = load_report(args.structure)

    summary_delta = build_summary_delta(
        fixed_summary=fixed_report["summary"],
        structure_summary=structure_report["summary"],
    )
    row_comparison = compare_rows(
        fixed_rows=fixed_report["rows"],
        structure_rows=structure_report["rows"],
    )

    report = {
        "fixed_report": str(args.fixed.resolve()),
        "structure_report": str(args.structure.resolve()),
        "fixed_config": fixed_report["config"],
        "structure_config": structure_report["config"],
        "summary_delta": summary_delta,
        "row_comparison": row_comparison,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== Chunking Comparison =====")
    for key, values in summary_delta.items():
        print(
            f"{key}: "
            f"{values['fixed']} -> {values['structure']} "
            f"({values['delta']:+})"
        )

    for group in (
        "improved",
        "regressed",
        "both_failed",
    ):
        rows = row_comparison[group]
        ids = [row["id"] for row in rows]
        print(f"{group}: {ids}")

    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())