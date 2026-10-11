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
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对比 vector 与 BM25 检索结果"
    )
    parser.add_argument(
        "--vector",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "semantic_chunk_baseline.json",
    )
    parser.add_argument(
        "--bm25",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S08_4_bm25_baseline.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S08_5_vector_vs_bm25.json",
    )
    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary_table(
    vector: dict[str, Any],
    bm25: dict[str, Any],
) -> dict[str, dict[str, float | int]]:
    table = {}

    for key in SUMMARY_KEYS:
        vector_value = vector["summary"][key]
        bm25_value = bm25["summary"][key]
        table[key] = {
            "vector": vector_value,
            "bm25": bm25_value,
            "delta_bm25_minus_vector": round(
                bm25_value - vector_value,
                4,
            ),
        }

    return table


def compare_cases(
    vector_rows: list[dict[str, Any]],
    bm25_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    vector_map = {row["id"]: row for row in vector_rows}
    bm25_map = {row["id"]: row for row in bm25_rows}

    result = {
        "vector_only_passed": [],
        "bm25_only_passed": [],
        "both_passed": [],
        "both_failed": [],
    }

    for case_id in sorted(vector_map):
        vector_row = vector_map[case_id]
        bm25_row = bm25_map[case_id]
        vector_ok = vector_row["retrieval_ok"]
        bm25_ok = bm25_row["retrieval_ok"]

        item = {
            "id": case_id,
            "category": vector_row["category"],
            "vector_ranks": vector_row["ranks"],
            "bm25_ranks": bm25_row["ranks"],
        }

        if vector_ok and not bm25_ok:
            result["vector_only_passed"].append(item)
        elif bm25_ok and not vector_ok:
            result["bm25_only_passed"].append(item)
        elif vector_ok and bm25_ok:
            result["both_passed"].append(item)
        else:
            result["both_failed"].append(item)

    return result


def main() -> int:
    args = parse_args()
    vector = load_report(args.vector)
    bm25 = load_report(args.bm25)

    summary_table = build_summary_table(vector, bm25)
    case_comparison = compare_cases(
        vector_rows=vector["rows"],
        bm25_rows=bm25["rows"],
    )

    vector_only = case_comparison["vector_only_passed"]
    bm25_only = case_comparison["bm25_only_passed"]
    both_passed = case_comparison["both_passed"]
    both_failed = case_comparison["both_failed"]

    report = {
        "summary_table": summary_table,
        "case_comparison": case_comparison,
        "coverage": {
            "vector_passed": len(vector_only) + len(both_passed),
            "bm25_passed": len(bm25_only) + len(both_passed),
            "union_passed": (
                len(vector_only)
                + len(bm25_only)
                + len(both_passed)
            ),
            "intersection_passed": len(both_passed),
            "vector_unique": len(vector_only),
            "bm25_unique": len(bm25_only),
            "both_failed": len(both_failed),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== Vector vs BM25 =====")
    for key, values in summary_table.items():
        print(
            f"{key}: "
            f"vector={values['vector']} "
            f"bm25={values['bm25']} "
            f"delta={values['delta_bm25_minus_vector']:+}"
        )

    print("\ncoverage:")
    for key, value in report["coverage"].items():
        print(f"{key}: {value}")

    for group, rows in case_comparison.items():
        print(f"{group}: {[row['id'] for row in rows]}")

    print(f"\nreport: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())