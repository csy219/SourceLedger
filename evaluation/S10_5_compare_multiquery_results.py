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
        description="对比 S09 RRF 与 S10 Multi-query"
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S09_4_hybrid_variants.json",
    )
    parser.add_argument(
        "--multi",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S10_3_multiquery_hybrid.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S10_5_multiquery_comparison.json",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_rows(
    base_rows: list[dict[str, Any]],
    multi_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    base_map = {row["id"]: row for row in base_rows}
    multi_map = {row["id"]: row for row in multi_rows}

    result = {
        "improved": [],
        "regressed": [],
        "both_failed": [],
        "top1_changed": [],
    }

    for case_id in sorted(base_map):
        base = base_map[case_id]
        multi = multi_map[case_id]

        item = {
            "id": case_id,
            "category": base["category"],
            "base_ranks": base["ranks"],
            "multi_ranks": multi["ranks"],
        }

        if (
            not base["retrieval_ok"]
            and multi["retrieval_ok"]
        ):
            result["improved"].append(item)
        elif (
            base["retrieval_ok"]
            and not multi["retrieval_ok"]
        ):
            result["regressed"].append(item)
        elif not multi["retrieval_ok"]:
            result["both_failed"].append(item)

        base_hits = base.get("hits", [])
        multi_hits = multi.get("hits", [])
        base_top1 = (
            (base_hits[0]["source"], base_hits[0]["page"])
            if base_hits
            else None
        )
        multi_top1 = (
            (multi_hits[0]["source"], multi_hits[0]["page"])
            if multi_hits
            else None
        )

        if base_top1 != multi_top1:
            top1_item = dict(item)
            top1_item["base_top1"] = base_top1
            top1_item["multi_top1"] = multi_top1
            result["top1_changed"].append(top1_item)

    return result


def main() -> int:
    args = parse_args()
    base_report = load_json(args.base)
    multi_report = load_json(args.multi)

    base_variant = base_report["variants"]["rrf"]
    base_summary = base_variant["summary"]
    multi_summary = multi_report["summary"]

    summary_table = {
        key: {
            "s09_rrf": base_summary[key],
            "s10_multi": multi_summary[key],
            "delta": round(
                multi_summary[key] - base_summary[key],
                4,
            ),
        }
        for key in SUMMARY_KEYS
    }

    case_comparison = compare_rows(
        base_rows=base_variant["rows"],
        multi_rows=multi_report["rows"],
    )
    changed_top1 = len(case_comparison["top1_changed"])
    total_cases = len(base_variant["rows"])

    report = {
        "summary_table": summary_table,
        "query_count_avg": multi_report["config"]["query_count_avg"],
        "fallback_count": multi_report["config"]["fallback_count"],
        "rewrite_latency_ms_avg": multi_report["config"][
            "rewrite_latency_ms_avg"
        ],
        "top1_same_rate": round(
            (total_cases - changed_top1) / total_cases,
            4,
        ),
        "top1_changed": changed_top1,
        "case_comparison": case_comparison,
        "selected_variant": "s09_rrf",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== S09 RRF vs S10 Multi-query =====")
    for key, values in summary_table.items():
        print(
            f"{key}: "
            f"s09_rrf={values['s09_rrf']} "
            f"s10_multi={values['s10_multi']} "
            f"delta={values['delta']:+}"
        )

    print(f"query_count_avg={report['query_count_avg']}")
    print(f"fallback_count={report['fallback_count']}")
    print(f"top1_same_rate={report['top1_same_rate']}")

    for group, items in case_comparison.items():
        print(f"{group}: {[item['id'] for item in items]}")

    print(f"selected_variant={report['selected_variant']}")
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())