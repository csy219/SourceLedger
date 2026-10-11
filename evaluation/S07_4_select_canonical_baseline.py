### 一、总体功能概述
# 这是**语义向量检索的基线定型脚本**，承接前面的参数网格扫描（S07_2），作用是从多组参数的扫描结果中，选出一套预设的标准参数作为官方「向量检索基线」，同时做质量一致性校验，最终输出结构化的基线报告。
# 它在整个流程中的定位：
# 1. 上游：S07_2 遍历所有 candidate_k /threshold 组合，输出全量扫描报告
# 2. 本脚本：校验扫描结果的一致性 → 选定目标参数 → 输出 canonical（标准 / 基准）基线
# 3. 下游：后续所有 RAG 优化（rerank 重排、父上下文扩展、混合检索等）都以这个基线为基准做效果对比

# 核心设计意图：
# - 先做一致性校验：确认在测试集上，不同召回数量、不同阈值的检索质量没有显著差异，说明检索效果稳定
# - 再选定标准配置：敲定一套官方参数，作为后续所有优化的参照基准，避免每次对比都换参数

import argparse
import json
from pathlib import Path
from typing import Any

TARGET_CANDIDATE_K=10
TARGET_THRESHOLD=0.5
TARGET_METRIC_K=4
QUALITY_KEYS=[
    "retrieval_passed",
    "hit_at_1",
    "hit_at_metric_k",
    "recall_at_metric_k",
    "mrr",
]


def parse_args()->argparse.Namespace:
    parser=argparse.ArgumentParser(
        description="从参数扫描结果中选择 canonical vector baseline"
    )
    parser.add_argument(
        "-sweep",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S07_2_semantic_vector_sweep.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S07_4_canonical_vector_baseline.json",
    )
    return parser.parse_args()


def load_json(path:Path)->dict[str,Any]:
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# - 功能：遍历所有参数组合的结果，精确匹配 `candidate_k=10、metric_k=4、threshold=0.5` 的目标配置，返回对应的完整结果。
# - 容错：如果没找到目标组合，直接抛出明确错误，提示参数不匹配。
def find_target_result(
    results:list[dict[str,Any]],
)->dict[str,Any]:
    for result in results:
        config=result["config"]
        if (
            config["candidate_k"]==TARGET_CANDIDATE_K
            and config["metric_k"]==TARGET_METRIC_K
            and config["threshold"]==TARGET_THRESHOLD
        ):
            return result

    raise ValueError(
        "参数扫描中没有找到 candidate_k=10,"
        "metric_k=4,threshold=0.5"
    )

def main()->int:
    args=parse_args()

    sweep=load_json(args.sweep)
    results=sweep.get("results",[])
    if not results:
        raise ValueError("参数扫描报告中没有 results")

    #   (例子) 一致性校验：
    # - 第 1 组指标元组：`(18, 0.75, 0.9, 0.95, 0.82)`
    # - 第 2 组指标元组：`(18, 0.75, 0.9, 0.95, 0.82)`
    # - 放入集合去重后长度 = 1，校验通过
    quality_signatures={
        tuple(result["summary"][key] for key in QUALITY_KEYS)
        for result in results
    }

    if len(quality_signatures) != 1:
        raise ValueError(
            "参数扫描的检索质量指标不一致，不能直接选择固定基线"
        )

    selected = find_target_result(results)

    report={
        "selection":{
            "chunk_mode":"semantic",
            "embedding_model":"BAAI/bge-small-zh-v1.5",
            "candidate_k":TARGET_CANDIDATE_K,
            "metric_k":TARGET_METRIC_K,
            "threshold":TARGET_THRESHOLD,
            "retrieval":"vector_only",
        },
        "reason": {
            "all_sweep_quality_metrics_equal": True,
            "candidate_k_10": (
                "为后续 rerank 和 source diversity 保留候选空间，"
                "同时控制上下文成本"
            ),
            "threshold_0_5": (
                "在 0.35-0.55 范围内无答案判定稳定，"
                "保持当前结果一致"
            ),
        },
        "sweep_source": str(args.sweep.resolve()),
        "summary": selected["summary"],
        "failed_ids": selected["failed_ids"],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("===== Canonical Vector Baseline =====")
    print("chunk_mode=semantic")
    print(f"candidate_k={TARGET_CANDIDATE_K}")
    print(f"metric_k={TARGET_METRIC_K}")
    print(f"threshold={TARGET_THRESHOLD}")
    print(f"retrieval_passed={selected['summary']['retrieval_passed']}")
    print(f"hit_at_1={selected['summary']['hit_at_1']}")
    print(f"hit_at_4={selected['summary']['hit_at_metric_k']}")
    print(f"recall_at_4={selected['summary']['recall_at_metric_k']}")
    print(f"mrr={selected['summary']['mrr']}")
    print(f"failed_ids={selected['failed_ids']}")
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())