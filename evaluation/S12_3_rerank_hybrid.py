import argparse
import copy
import json
import math
import time
from pathlib import Path
from typing import Any

from run_fixed_chunk_baseline import build_summary
from S06_2_parent_child_index import build_parents_and_children
from S08_3_bm25_index import BM25Index
from S09_2_rrf_fusion import fuse_rrf
from S09_4_hybrid_eval import evaluate_variant, load_collection
from S11_2_metadata_intent import (
    build_chroma_where,
    parse_metadata_intent,
)
from S11_3_filtered_hybrid import (
    query_vector_hits,
    search_bm25_with_sources,
)
from S12_2_reranker_adapter import Reranker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 Metadata Filter + RRF + Reranker"
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path(__file__).parent / "eval_set.json",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).parent / "corpus",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).parent / "baseline.chroma",
    )
    parser.add_argument(
        "--collection",
        default="semantic_chunk_baseline",
    )
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument(
        "--semantic-threshold",
        type=float,
        default=0.72,
    )
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--metric-k", type=int, default=4)
    parser.add_argument("--distance-threshold", type=float, default=0.5)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--reranker-model",
        default="BAAI/bge-reranker-v2-m3",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S12_3_rerank_hybrid.json",
    )
    return parser.parse_args()


#### 二元 NDCG@K 指标 `binary_ndcg_at_k()`
# 信息检索领域的核心排序质量指标，此处实现**二元相关性版本**（相关得 1 分、不相关得 0 分）。

# - 输入：检索命中结果列表、标准答案源文档、截断位置 k
# - 计算逻辑：
#   1. 将标准答案转为`(source, page)`元组集合，完成去重
#   2. 遍历前 k 个命中结果，按顺序生成增益序列：相关则增益为 1，否则为 0
#   3. 计算 DCG（折损累计增益）：每个增益除以`log2(排名+2)`后求和
#   4. 计算 IDCG（理想 DCG）：所有相关结果全部排在最前时的 DCG 值
#   5. 最终`NDCG = DCG / IDCG`，值域 0~1，越接近 1 表示排序效果越好
# - 边界处理：标准答案为空、IDCG 为 0 时直接返回 0。
def binary_ndcg_at_k(
    hits:list[dict[str,Any]],
    expected_sources:list[dict[str,Any]],
    k:int,
)->float:
    relevant={
        (item["source"],item["page"])
        for item in expected_sources
    }
    if not relevant:
        return 0.0

    gains=[]
    seen_relevant=set()

    for hit in hits[:k]:
        key=(hit["source"],hit["page"])
        if key in relevant and key not in seen_relevant:
            gains.append(1.0)
            seen_relevant.add(key)

        else:
            gains.append(0.0)
    dcg=sum(
        gain/math.log2(index+2)
        for index,gain in enumerate(gains)
    )

    ideal_count=min(len(relevant),k)
    idcg=sum(
        1.0/math.log2(index+2)
        for index in range(ideal_count)
    )

    return dcg / idcg if idcg else 0.0


def main()->int:
    args=parse_args()

    document=json.loads(
        args.eval_set.read_text(encoding="utf-8")
    )
    cases=document.get("cases",[])

    collection=load_collection(args.db,args.collection)
    _,children=build_parents_and_children(
        corpus_dir=args.corpus,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        semantic_threshold=args.semantic_threshold,
    )

    bm25_index=BM25Index()
    bm25_index.fit(children)

    reranker=Reranker(
        model_name=args.reranker_model,
        device=args.device,
    )
    no_rerank_rows = []
    rerank_rows = []
    filter_applied_count = 0
    filter_fallback_count = 0
    rerank_latencies = []


    for case in cases:
        intent=parse_metadata_intent(case["question"])
        sources=set(intent["sources"])
        where=build_chroma_where(intent["sources"])

        vector_hits,vector_latency=query_vector_hits(
            collection=collection,
            question=case["question"],
            candidate_k=args.candidate_k,
            where=where,
        )

        bm25_hits,bm25_latency=search_bm25_with_sources(
            index=bm25_index,
            question=case["question"],
            sources=sources,
            candidate_k=args.candidate_k,
        )

        used_fallback=False
        if where is not None and not vector_hits and not bm25_hits:
            used_fallback = True
            filter_fallback_count += 1
            vector_hits, vector_latency = query_vector_hits(
                collection=collection,
                question=case["question"],
                candidate_k=args.candidate_k,
                where=None,
            )
            bm25_hits, bm25_latency = search_bm25_with_sources(
                index=bm25_index,
                question=case["question"],
                sources=set(),
                candidate_k=args.candidate_k,
            )

        if where is not None and not used_fallback:
            filter_applied_count+=1

        rrf_hits=fuse_rrf(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            k=args.rrf_k,
            top_k=args.candidate_k
        )

        retrieval_latency_ms=vector_latency+bm25_latency

        # 没有rerank 的结果
        no_rerank_row = evaluate_variant(
            case=case,
            hits=rrf_hits,
            latency_ms=retrieval_latency_ms,
            vector_hits=vector_hits,
            metric_k=args.metric_k,
            distance_threshold=args.distance_threshold,
        )
        no_rerank_row["ndcg_at_4"] = binary_ndcg_at_k(
            hits=rrf_hits,
            expected_sources=case["expected_sources"],
            k=args.metric_k,
        )
        no_rerank_rows.append(no_rerank_row)


        #有 rerank 的结果
        rerank_input=copy.deepcopy(rrf_hits)
        rerank_started=time.perf_counter()
        reranked_hits=reranker.rerank(
            question=case["question"],
            candidates=rerank_input,
            top_k=args.metric_k,
            batch_size=args.batch_size,
        )
        rerank_latency_ms=(
            time.perf_counter()-rerank_started
        )*1000

        rerank_latencies.append(rerank_latency_ms)

        rerank_row = evaluate_variant(
            case=case,
            hits=reranked_hits,
            latency_ms=retrieval_latency_ms + rerank_latency_ms,
            vector_hits=vector_hits,
            metric_k=args.metric_k,
            distance_threshold=args.distance_threshold,
        )
        rerank_row["ndcg_at_4"] = binary_ndcg_at_k(
            hits=reranked_hits,
            expected_sources=case["expected_sources"],
            k=args.metric_k,
        )
        rerank_row["rerank_candidates"] = [
            {
                "child_id": candidate["child_id"],
                "source": candidate["source"],
                "page": candidate["page"],
                "rrf_score": candidate.get("rrf_score"),
                "rrf_rank": candidate.get("rrf_rank"),
                "rerank_score": candidate.get("rerank_score"),
                "rerank_rank": candidate.get("rerank_rank"),
            }
            for candidate in reranked_hits
        ]
        rerank_rows.append(rerank_row)

    no_rerank_summary = build_summary(
        no_rerank_rows,
        args.metric_k,
    )
    rerank_summary = build_summary(
        rerank_rows,
        args.metric_k,
    )
    no_rerank_summary["ndcg_at_4"] = round(
        sum(row["ndcg_at_4"] for row in no_rerank_rows)
        / len(no_rerank_rows),
        4,
    )
    rerank_summary["ndcg_at_4"] = round(
        sum(row["ndcg_at_4"] for row in rerank_rows)
        / len(rerank_rows),
        4,
    )

    report = {
        "config": {
            "candidate_k": args.candidate_k,
            "metric_k": args.metric_k,
            "distance_threshold": args.distance_threshold,
            "rrf_k": args.rrf_k,
            "reranker_backend": reranker.backend,
            "reranker_model": reranker.model_name,
            "reranker_device": reranker.device,
            "reranker_load_ms": round(reranker.load_ms, 2),
            "reranker_load_error": reranker.load_error,
            "rerank_latency_ms_avg": round(
                sum(rerank_latencies) / len(rerank_latencies),
                2,
            ),
            "filter_applied_count": filter_applied_count,
            "filter_fallback_count": filter_fallback_count,
        },
        "variants": {
            "filtered_hybrid_k20": {
                "summary": no_rerank_summary,
                "failed_ids": [
                    row["id"] for row in no_rerank_rows
                    if not row["retrieval_ok"]
                ],
                "rows": no_rerank_rows,
            },
            "rerank_k20": {
                "summary": rerank_summary,
                "failed_ids": [
                    row["id"] for row in rerank_rows
                    if not row["retrieval_ok"]
                ],
                "rows": rerank_rows,
            },
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for name, variant in report["variants"].items():
        print(f"\n===== {name} =====")
        for key, value in variant["summary"].items():
            print(f"{key}: {value}")
        print(f"failed_ids={variant['failed_ids']}")

    print(f"\nreranker_backend={reranker.backend}")
    print(f"reranker_model={reranker.model_name}")
    print(f"reranker_load_ms={reranker.load_ms:.2f}")
    print(
        f"rerank_latency_ms_avg="
        f"{report['config']['rerank_latency_ms_avg']}"
    )
    print(f"report: {args.output.resolve()}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())



