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
        description="对比 S09 RRF 与 S11 Metadata Filter Hybrid"
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S09_4_hybrid_variants.json",
    )
    parser.add_argument(
        "--filtered",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S11_3_filtered_hybrid.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S11_5_filtered_comparison.json",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_rows(
    base_rows: list[dict[str, Any]],
    filtered_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    base_map = {row["id"]: row for row in base_rows}
    filtered_map = {row["id"]: row for row in filtered_rows}

    result = {
        "improved": [],
        "regressed": [],
        "both_failed": [],
        "top1_changed": [],
        "filtered_rank_changed": [],
    }

    for case_id in sorted(base_map):
        base = base_map[case_id]
        filtered = filtered_map[case_id]

        item = {
            "id": case_id,
            "category": base["category"],
            "base_ranks": base["ranks"],
            "filtered_ranks": filtered["ranks"],
            "filter": filtered.get("filter", {}),
        }

        if (
            not base["retrieval_ok"]
            and filtered["retrieval_ok"]
        ):
            result["improved"].append(item)
        elif (
            base["retrieval_ok"]
            and not filtered["retrieval_ok"]
        ):
            result["regressed"].append(item)
        elif not filtered["retrieval_ok"]:
            result["both_failed"].append(item)

        base_hits = base.get("hits", [])
        filtered_hits = filtered.get("hits", [])
        base_top1 = (
            (base_hits[0]["source"], base_hits[0]["page"])
            if base_hits
            else None
        )
        filtered_top1 = (
            (filtered_hits[0]["source"], filtered_hits[0]["page"])
            if filtered_hits
            else None
        )

        if base_top1 != filtered_top1:
            top1_item = dict(item)
            top1_item["base_top1"] = base_top1
            top1_item["filtered_top1"] = filtered_top1
            result["top1_changed"].append(top1_item)

        if (
            item["filter"].get("applied")
            and base["ranks"] != filtered["ranks"]
        ):
            result["filtered_rank_changed"].append(item)

    return result


def main() -> int:
    args = parse_args()
    base_report = load_json(args.base)
    filtered_report = load_json(args.filtered)

    base_variant = base_report["variants"]["rrf"]
    base_summary = base_variant["summary"]
    filtered_summary = filtered_report["summary"]

    summary_table = {
        key: {
            "s09_rrf": base_summary[key],
            "s11_filtered": filtered_summary[key],
            "delta": round(
                filtered_summary[key] - base_summary[key],
                4,
            ),
        }
        for key in SUMMARY_KEYS
    }

    comparison = compare_rows(
        base_rows=base_variant["rows"],
        filtered_rows=filtered_report["rows"],
    )

    no_regression = not comparison["regressed"]
    no_metric_loss = all(
        summary_table[key]["delta"] >= 0
        for key in (
            "retrieval_passed",
            "hit_at_1",
            "hit_at_metric_k",
            "recall_at_metric_k",
            "mrr",
        )
    )
    selected_variant = (
        "s11_filtered"
        if no_regression and no_metric_loss
        else "s09_rrf"
    )

    report = {
        "summary_table": summary_table,
        "filter_config": filtered_report["config"],
        "case_comparison": comparison,
        "selected_variant": selected_variant,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== S09 RRF vs S11 Metadata Filter =====")
    for key, values in summary_table.items():
        print(
            f"{key}: "
            f"s09_rrf={values['s09_rrf']} "
            f"s11_filtered={values['s11_filtered']} "
            f"delta={values['delta']:+}"
        )

    print(
        f"filter_applied_count="
        f"{filtered_report['config']['filter_applied_count']}"
    )
    print(
        f"filter_fallback_count="
        f"{filtered_report['config']['filter_fallback_count']}"
    )

    for group, items in comparison.items():
        print(f"{group}: {[item['id'] for item in items]}")

    print(f"selected_variant={selected_variant}")
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())