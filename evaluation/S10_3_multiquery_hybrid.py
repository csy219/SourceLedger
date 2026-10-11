import argparse
import json
import math
import time

from pathlib import Path
from typing import Any

from run_fixed_chunk_baseline import build_summary
from S06_2_parent_child_index import build_parents_and_children
from S08_3_bm25_index import BM25Index
from S09_4_hybrid_eval import (
    evaluate_variant,
    load_collection,
    query_vector_hits
)
from S10_2_query_rewrite import build_fallback_rewrite

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行多查询 Hybrid 检索"
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
    parser.add_argument(
        "--rewrites",
        type=Path,
        default=Path(__file__).parent
        / "query_rewrite"
        / "S10_2_rewrites.json",
    )
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument(
        "--semantic-threshold",
        type=float,
        default=0.72,
    )
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--metric-k", type=int, default=4)
    parser.add_argument("--distance-threshold", type=float, default=0.5)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S10_3_multiquery_hybrid.json",
    )
    return parser.parse_args()

# 加载查询改写缓存
def load_rewrites(path:Path)->dict[str,dict[str,Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"改写缓存不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

# 构造多查询列表
def build_queries(record:dict[str,Any])->list[str]:
    candidates=[
        record.get("original",""),
        record.get("semantic",""),
        record.get("keyword_query","")
    ]
    queries=[]
    seen=set()

    for query in candidates:
        normalized=query.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        queries.append(normalized)
    return queries

# `fuse_multi_query_rrf()`：RRF 结果融合（核心算法）
def fuse_multi_query_rrf(
    ranked_groups:list[tuple[str,list[dict[str,Any]]]],
    k:int,
    top_k:int,
)->list[dict[str,Any]]:
    fused:dict[str,dict[str,Any]]={}

    for retriever,hits in ranked_groups:
        for rank,hit in enumerate(hits,start=1):
            child_id=hit.get("child_id","")
            item=fused.setdefault(
                child_id,
                {
                    "child_id":child_id,
                    "source":hit["source"],
                    "page":hit["page"],
                    "text":hit.get("text",""),
                    "rrf_score":0.0,
                    "best_vector_rank":None,
                    "best_bm25_rank":None,
                    "contributions":0
                },
            )
            item["rrf_score"]+=1.0/(rank+k)
            item["contributions"]+=1

            if retriever=="vector":
                current=item["best_vector_rank"]
                if current is None or rank <current:
                    item["best_vector_rank"]=rank
            else:
                current=item["best_bm25_rank"]
                if current is None or rank < current:
                    item["best_bm25_rank"]=rank

    ordered = sorted(
        fused.values(),
        key=lambda item: (
            -item["rrf_score"],
            item["best_vector_rank"]
            if item["best_vector_rank"] is not None
            else math.inf,
            item["best_bm25_rank"]
            if item["best_bm25_rank"] is not None
            else math.inf,
            item["child_id"],
        ),
    )

    for rank,item in enumerate(ordered[:top_k],start=1):
        item["rank"]=rank
        item["rrf_score"]=round(item["rrf_score"],8)

    return ordered[:top_k]

def main() -> int:
    args = parse_args()

    document = json.loads(
        args.eval_set.read_text(encoding="utf-8")
    )
    cases = document.get("cases", [])
    rewrites = load_rewrites(args.rewrites)
    collection = load_collection(args.db, args.collection)

    _, children = build_parents_and_children(
        corpus_dir=args.corpus,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        semantic_threshold=args.semantic_threshold,
    )
    bm25_index = BM25Index()
    bm25_index.fit(children)

    rows = []
    query_counts = []
    fallback_count = 0
    rewrite_latency_total = 0.0

    for case in cases:
        record = rewrites.get(case["question"])
        if record is None:
            record = build_fallback_rewrite(case["question"])

        if record.get("rewrite_status") == "fallback":
            fallback_count += 1

        rewrite_latency_total += float(
            record.get("rewrite_latency_ms", 0.0)
        )

        queries = build_queries(record)
        query_counts.append(len(queries))

        ranked_groups: list[
            tuple[str, list[dict[str, Any]]]
        ] = []
        total_latency_ms = 0.0
        original_vector_hits: list[dict[str, Any]] = []

        for query_index, query in enumerate(queries):
            vector_hits, vector_latency = query_vector_hits(
                collection=collection,
                question=query,
                candidate_k=args.candidate_k,
            )

            bm25_started = time.perf_counter()
            bm25_hits = bm25_index.search(
                query=query,
                top_k=args.candidate_k,
            )
            bm25_latency = (
                time.perf_counter() - bm25_started
            ) * 1000

            if query_index == 0:
                original_vector_hits = vector_hits

            ranked_groups.append(("vector", vector_hits))
            ranked_groups.append(("bm25", bm25_hits))
            total_latency_ms += vector_latency + bm25_latency

        fused_hits = fuse_multi_query_rrf(
            ranked_groups=ranked_groups,
            k=args.rrf_k,
            top_k=args.candidate_k,
        )

        rows.append(
            evaluate_variant(
                case=case,
                hits=fused_hits,
                latency_ms=total_latency_ms,
                vector_hits=original_vector_hits,
                metric_k=args.metric_k,
                distance_threshold=args.distance_threshold,
            )
        )

    summary = build_summary(rows, args.metric_k)
    report = {
        "config": {
            "retrieval": "multi_query_rrf",
            "candidate_k": args.candidate_k,
            "metric_k": args.metric_k,
            "distance_threshold": args.distance_threshold,
            "rrf_k": args.rrf_k,
            "query_count_avg": round(
                sum(query_counts) / len(query_counts),
                3,
            ),
            "fallback_count": fallback_count,
            "rewrite_latency_ms_avg": round(
                rewrite_latency_total / len(cases),
                2,
            ),
        },
        "summary": summary,
        "failed_ids": [
            row["id"] for row in rows
            if not row["retrieval_ok"]
        ],
        "rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== Multi-query Hybrid =====")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"query_count_avg={report['config']['query_count_avg']}")
    print(f"fallback_count={fallback_count}")
    print(f"failed_ids={report['failed_ids']}")
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





    