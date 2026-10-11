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
        description="对比 Hybrid 检索变体"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S09_4_hybrid_variants.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S09_5_hybrid_comparison.json",
    )
    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary_table(
    variants: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    table = {}
    for key in SUMMARY_KEYS:
        table[key] = {
            name: variant["summary"][key]
            for name, variant in variants.items()
        }
    return table


def compare_against_vector(
    vector_rows: list[dict[str, Any]],
    variant_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    vector_map = {row["id"]: row for row in vector_rows}
    variant_map = {row["id"]: row for row in variant_rows}

    result = {
        "improved": [],
        "regressed": [],
        "both_failed": [],
    }

    for case_id in sorted(vector_map):
        vector_row = vector_map[case_id]
        variant_row = variant_map[case_id]

        item = {
            "id": case_id,
            "category": vector_row["category"],
            "vector_ranks": vector_row["ranks"],
            "variant_ranks": variant_row["ranks"],
        }

        if (
            not vector_row["retrieval_ok"]
            and variant_row["retrieval_ok"]
        ):
            result["improved"].append(item)
        elif (
            vector_row["retrieval_ok"]
            and not variant_row["retrieval_ok"]
        ):
            result["regressed"].append(item)
        elif not variant_row["retrieval_ok"]:
            result["both_failed"].append(item)

    return result


def choose_best_variant(
    variants: dict[str, dict[str, Any]],
) -> str:
    return max(
        variants,
        key=lambda name: (
            variants[name]["summary"]["retrieval_passed"],
            variants[name]["summary"]["mrr"],
            variants[name]["summary"]["hit_at_1"],
        ),
    )


def main() -> int:
    args = parse_args()
    report = load_report(args.report)
    variants = report["variants"]

    summary_table = build_summary_table(variants)
    vector_rows = variants["vector"]["rows"]

    comparisons = {
        name: compare_against_vector(
            vector_rows=vector_rows,
            variant_rows=variant["rows"],
        )
        for name, variant in variants.items()
        if name != "vector"
    }

    best_variant = choose_best_variant(variants)
    output = {
        "summary_table": summary_table,
        "best_variant": best_variant,
        "comparisons_vs_vector": comparisons,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== Hybrid Variant Comparison =====")
    for key, values in summary_table.items():
        print(
            f"{key}: "
            + " ".join(
                f"{name}={value}"
                for name, value in values.items()
            )
        )

    print(f"\nbest_variant: {best_variant}")

    for name, comparison in comparisons.items():
        print(f"\n{name} vs vector")
        for group in ("improved", "regressed", "both_failed"):
            ids = [item["id"] for item in comparison[group]]
            print(f"  {group}: {ids}")

    print(f"\nreport: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())