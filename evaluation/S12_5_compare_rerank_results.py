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
    "ndcg_at_4",
    "latency_ms_avg",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对比 rerank 前后结果"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S12_3_rerank_hybrid.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S12_5_rerank_comparison.json",
    )
    return parser.parse_args()


def load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"报告不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_ranks(
    base_ranks: list[int | None],
    rerank_ranks: list[int | None],
) -> dict[str, Any]:
    promoted = []
    demoted = []
    unchanged = []

    for index, (base, reranked) in enumerate(
        zip(base_ranks, rerank_ranks),
        start=1,
    ):
        item = {
            "expected_index": index,
            "base_rank": base,
            "rerank_rank": reranked,
        }
        base_value = base if base is not None else 10**9
        rerank_value = reranked if reranked is not None else 10**9

        if rerank_value < base_value:
            promoted.append(item)
        elif rerank_value > base_value:
            demoted.append(item)
        else:
            unchanged.append(item)

    return {
        "promoted": promoted,
        "demoted": demoted,
        "unchanged": unchanged,
    }


def main() -> int:
    args = parse_args()
    report = load_report(args.report)

    base_variant = report["variants"]["filtered_hybrid_k20"]
    rerank_variant = report["variants"]["rerank_k20"]
    base_rows = base_variant["rows"]
    rerank_rows = rerank_variant["rows"]

    summary_table = {
        key: {
            "no_rerank": base_variant["summary"][key],
            "rerank": rerank_variant["summary"][key],
            "delta": round(
                rerank_variant["summary"][key]
                - base_variant["summary"][key],
                4,
            ),
        }
        for key in SUMMARY_KEYS
    }

    base_map = {row["id"]: row for row in base_rows}
    rerank_map = {row["id"]: row for row in rerank_rows}

    improved = []
    regressed = []
    both_failed = []
    top1_changed = []
    rank_changes = {}

    for case_id in sorted(base_map):
        base = base_map[case_id]
        reranked = rerank_map[case_id]
        base_ok = base["retrieval_ok"]
        rerank_ok = reranked["retrieval_ok"]

        item = {
            "id": case_id,
            "category": base["category"],
            "base_ranks": base["ranks"],
            "rerank_ranks": reranked["ranks"],
            "rank_changes": compare_ranks(
                base_ranks=base["ranks"],
                rerank_ranks=reranked["ranks"],
            ),
        }

        if not base_ok and rerank_ok:
            improved.append(item)
        elif base_ok and not rerank_ok:
            regressed.append(item)
        elif not rerank_ok:
            both_failed.append(item)

        base_hits = base.get("hits", [])
        rerank_hits = reranked.get("hits", [])
        base_top1 = (
            (base_hits[0]["source"], base_hits[0]["page"])
            if base_hits else None
        )
        rerank_top1 = (
            (rerank_hits[0]["source"], rerank_hits[0]["page"])
            if rerank_hits else None
        )

        if base_top1 != rerank_top1:
            top1_item = dict(item)
            top1_item["base_top1"] = base_top1
            top1_item["rerank_top1"] = rerank_top1
            top1_changed.append(top1_item)

        if case_id in {"E33", "E31", "E34"}:
            rank_changes[case_id] = item

    output = {
        "summary_table": summary_table,
        "improved": improved,
        "regressed": regressed,
        "both_failed": both_failed,
        "top1_changed": top1_changed,
        "selected_variant": "filtered_hybrid_k20",
        "focused_cases": rank_changes,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("===== Rerank Comparison =====")
    for key, values in summary_table.items():
        print(
            f"{key}: "
            f"no_rerank={values['no_rerank']} "
            f"rerank={values['rerank']} "
            f"delta={values['delta']:+}"
        )

    for group, items in (
        ("improved", improved),
        ("regressed", regressed),
        ("both_failed", both_failed),
        ("top1_changed", top1_changed),
    ):
        print(f"{group}: {[item['id'] for item in items]}")

    print("\nfocused_cases:")
    for case_id, item in rank_changes.items():
        print(
            f"{case_id}: "
            f"{item['base_ranks']} -> {item['rerank_ranks']} "
            f"changes={item['rank_changes']}"
        )

    print(f"\nselected_variant={output['selected_variant']}")
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())