# 逐行解析：对比报告生成器（compare_reports.py）

## 整体定位
# 这是 **S14 Harness 的「报告层核心模块」**，对应你规划的 `reports.py` 的完整对比能力。
# 它的定位是：**批量跑完所有 runner 之后，自动做横向对比、差异分析、最优判定，同时输出机器可读的 JSON 报告和人可读的 Markdown 表格**。
# 不用人工一个个对着数字比，自动告诉你：哪个模式效果最好、混合检索解决了哪些题、又退步了哪些题、所有模式都搞不定的难题有哪些。

import argparse
import json
from pathlib import Path
from typing import Any

from config import HarnessConfig
from dataset import EvalDataset


RUNNERS = [
    "vector",
    "bm25",
    "hybrid",
]

HIGHER_IS_BETTER = {
    "retrieval_accuracy",
    "hit_at_1",
    "hit_at_k",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
}

LOWER_IS_BETTER = {
    "latency_ms_avg",
    "context_tokens_avg",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对比 Harness runner 报告"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent
        / "configs"
        / "core.json",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).parent
        / "reports",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "core_comparison.json",
    )
    return parser.parse_args()


def load_report(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"报告不存在: {path}"
        )
    return json.loads(
        path.read_text(encoding="utf-8")
    )

def build_best_metrics(
        summaries:dict[str,dict[str,Any]],
)->dict[str,dict[str,Any]]:
    result:dict[str,dict[str,Any]]={}

    for metric in(
        HIGHER_IS_BETTER |LOWER_IS_BETTER
    ):
        values={
            runner:summary.get(metric)
            for runner,summary in summaries.items()
            if summary.get(metric) is not None
        }
        if not values:
            result[metric]={
                "best_runner":None,
                "best_values":None,
            }
            continue
        if metric in HIGHER_IS_BETTER:
            best_runner=max(
                values,
                key=values.get,
            )
        else:
            best_runner = min(
                values,
                key=values.get,
            )

        result[metric] = {
            "best_runner": best_runner,
            "best_value": values[best_runner],
        }

    return result

def main()->int:
    args=parse_args()

    config=HarnessConfig.from_json(args.config)

    dataset=EvalDataset.from_json(config.eval_set)


    # - `reports`：存每个 runner 的完整报告（含单例详情），用来做 case 级差异分析
    # - `summaries`：存每个 runner 的汇总指标，用来算整体对比和最优值
    reports: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}

    for runner in RUNNERS:
        path = args.report_dir / f"{runner}.json"
        reports[runner] = load_report(path)
        summaries[runner] = reports[runner].get(
            "summary",
            {},
        )
    # 调用上面的函数，得到每个指标的最优模式。
    best_metrics = build_best_metrics(summaries)

    # 建立「case_id → 分类」的字典，后面做分类失败统计用。
    category_by_id = {
        case.id: case.category
        for case in dataset.cases
    }
    all_case_ids = sorted(category_by_id)

    ### . 核心：Case 级差异分析
    # 这是整个脚本最有价值的部分，**不只是比整体数字，还深入到单题层面，分析模式之间的优劣变化**。
    # ① 每个 runner 的检索失败列表
    retrieval_failed = {
        runner: [
            row["case_id"]
            for row in reports[runner]["rows"]
            if not row["retrieval_ok"]
        ]
        for runner in RUNNERS
    }
    # ② 全模式共同失败
    all_failed=[
        case_id
        for case_id in all_case_ids
        if all(
            case_id in retrieval_failed[runner]
            for runner in RUNNERS
        )
    ]
    # ③ 混合检索增益（hybrid_fixes）
    hybrid_fixes = [
        case_id
        for case_id in all_case_ids
        if (
            case_id not in retrieval_failed["hybrid"]
            and case_id in retrieval_failed["vector"]
            and case_id in retrieval_failed["bm25"]
        )
    ]
    # ④ 混合检索退步（hybrid_regressions）
    hybrid_regressions = [
        case_id
        for case_id in all_case_ids
        if (
            case_id in retrieval_failed["hybrid"]
            and (
                case_id not in retrieval_failed["vector"]
                or case_id not in retrieval_failed["bm25"]
            )
        )
    ]
    # 6. 分类失败统计
    category_failures:dict[
        str,
        dict[str,Any],
    ]={}

    for runner in RUNNERS:
        counts:dict[str,int]={}
        for case_id in retrieval_failed[runner]:
            category=category_by_id.get(
                case_id,
                "unknown",
            )
            counts[category]=(
                counts.get(category,0)+1
            )
        category_failures[runner]=counts

    comparison = {
        "config": {
            "metric_k": config.metric_k,
            "candidate_k": config.candidate_k,
        },
        "summaries": summaries,
        "best_metrics": best_metrics,
        "case_differences": {
            "all_failed": all_failed,
            "hybrid_fixes": hybrid_fixes,
            "hybrid_regressions": hybrid_regressions,
            "retrieval_failed": retrieval_failed,
        },
        "category_failures": category_failures,
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            comparison,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    ### 生成 Markdown 可视化报告
    # 自动生成人可读的表格，不用手动整理 Excel。
    # ① 汇总对比表
    markdown_path = args.output.with_suffix(
        ".md"
    )
    lines = [
        "# Harness Core Comparison",
        "",
        "## Summary",
        "",
        (
            "| runner | retrieval_accuracy | "
            "hit_at_1 | hit_at_k | recall_at_k | "
            "mrr | ndcg_at_k | latency_ms_avg | "
            "context_tokens_avg |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for runner in RUNNERS:
        summary = summaries[runner]
        lines.append(
            f"| {runner} "
            f"| {summary.get('retrieval_accuracy')} "
            f"| {summary.get('hit_at_1')} "
            f"| {summary.get('hit_at_k')} "
            f"| {summary.get('recall_at_k')} "
            f"| {summary.get('mrr')} "
            f"| {summary.get('ndcg_at_k')} "
            f"| {summary.get('latency_ms_avg')} "
            f"| {summary.get('context_tokens_avg')} |"
        )

    # ② 失败分析 + 最优指标
    lines.extend(
        [
            "",
            "## Failures",
            "",
            f"- all_failed={all_failed}",
            f"- hybrid_fixes={hybrid_fixes}",
            f"- hybrid_regressions={hybrid_regressions}",
            "",
            "## Best Metrics",
            "",
        ]
    )
    for metric, value in best_metrics.items():
        lines.append(
            f"- {metric}: "
            f"{value['best_runner']} "
            f"({value['best_value']})"
        )

    markdown_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


    # 控制台打印核心结论
    print("===== Core Comparison =====")
    print(f"all_failed={all_failed}")
    print(f"hybrid_fixes={hybrid_fixes}")
    print(f"hybrid_regressions={hybrid_regressions}")

    for runner in RUNNERS:
        summary = summaries[runner]
        print(
            f"{runner}: "
            f"Hit@1={summary.get('hit_at_1')} "
            f"Recall@4={summary.get('recall_at_k')} "
            f"MRR={summary.get('mrr')} "
            f"nDCG@4={summary.get('ndcg_at_k')} "
            f"tokens_avg="
            f"{summary.get('context_tokens_avg')}"
        )

    print(f"report={args.output.resolve()}")
    print(f"markdown={markdown_path.resolve()}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())