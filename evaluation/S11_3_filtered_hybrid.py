# 1. 解析评测集每一条 query，通过`parse_metadata_intent`从问题里提取用户意图：限定文档源`sources`、过滤原因`reason`；
# 2. 构造 Chroma 的`where`元数据过滤条件，**向量检索带上文档源过滤**；同时 BM25 检索也只在指定 sources 内检索；
# 3. 兜底策略：如果过滤后向量、BM25 都没有返回结果 → 关闭过滤，全库检索（fallback）；
# 4. 向量检索结果 + BM25 检索结果，使用 RRF 融合重排；
# 5. 对融合后的结果做指标评估，收集每条 case 记录；
# 6. 汇总指标、统计过滤 / 回退数量，输出完整 json 报告。

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT=Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from pdf_rag import embed
from run_fixed_chunk_baseline import build_summary
from S06_2_parent_child_index import build_parents_and_children
from S08_3_bm25_index import BM25Index
from S09_2_rrf_fusion import fuse_rrf
from S09_4_hybrid_eval import evaluate_variant,load_collection
from S11_2_metadata_intent import(
    build_chroma_where,
    parse_metadata_intent
)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 Metadata Filter + RRF Hybrid"
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
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--metric-k", type=int, default=4)
    parser.add_argument("--distance-threshold", type=float, default=0.5)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S11_3_filtered_hybrid.json",
    )
    return parser.parse_args()

# 向量检索+过滤
def query_vector_hits(
        collection:Any,
        question:str,
        candidate_k:int,
        where:dict[str,Any] | None,
)->tuple[list[dict[str,Any]],float]:
    started=time.perf_counter()
    arguments:dict[str,Any]={
        "query_embeddings":embed([question]),
        "n_results":candidate_k,
        "include":["documents","metadatas","distances"]
    }

    if where is not None:
        arguments["where"]=where

    # Chroma 不支持把一个参数字典作为位置参数传进去。
    # 应该展开成关键字参数：
    result=collection.query(**arguments)
    latency_ms=(time.perf_counter()-started)*1000

    ids=result.get("ids",[[]])[0]
    hits=[]

    for child_id,document,metadata,distance in zip(
        ids,
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0]
    ):
        hits.append(
            {
                "child_id":child_id,
                "source":metadata["source"],
                "page":metadata["page"],
                "text":document,
                "distance":round(float(distance),4)
            }
        )

    return hits,latency_ms

# 关键词检索+过滤
def search_bm25_with_sources(
        index:BM25Index,
        question:str,
        sources:set[str],
        candidate_k:int,
)->tuple[list[dict[str,Any]],float]:
    started=time.perf_counter()
    all_hits=index.search(
        query=question,
        top_k=len(index.documents)
    )

    latency_ms=(time.perf_counter()-started)*1000

    if not sources:
        return all_hits[:candidate_k],latency_ms

    filtered=[
        hit
        for hit in all_hits
        if hit["source"] in sources
    ]
    return filtered[:candidate_k],latency_ms

def main()->int:
    args=parse_args()

    document=json.loads(args.eval_set.read_text(encoding="utf-8"))
    cases=document.get("cases",[])
    collection=load_collection(args.db,args.collection)

    _,children =build_parents_and_children(
        corpus_dir=args.corpus,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        semantic_threshold=args.semantic_threshold,
    )

    bm25_index=BM25Index()
    bm25_index.fit(children)

    rows=[]
    filter_applied_count = 0
    filter_fallback_count = 0
    filter_reasons: dict[str, int] = {}

    for case in cases:
        intent=parse_metadata_intent(case["question"])
        sources=set(intent["sources"])
        where=build_chroma_where(intent["sources"])
        filter_reasons[intent["reason"]]=(
            filter_reasons.get(intent["reason"],0)+1
        )

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
        # 
        used_fallback = False
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
                filter_applied_count += 1


        fused_hits = fuse_rrf(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            k=args.rrf_k,
            top_k=args.candidate_k,
        )

        row=evaluate_variant(
            case=case,
            hits=fused_hits,
            latency_ms=vector_latency+bm25_latency,
            vector_hits=vector_hits,
            metric_k=args.metric_k,
            distance_threshold=args.distance_threshold,
        )
        row["filter"] = {
            "sources": sorted(sources),
            "reason": intent["reason"],
            "applied": where is not None and not used_fallback,
            "fallback": used_fallback,
        }
        rows.append(row)
    summary = build_summary(rows, args.metric_k)
    report = {
    "config": {
        "retrieval": "metadata_filter_rrf",
        "candidate_k": args.candidate_k,
        "metric_k": args.metric_k,
        "distance_threshold": args.distance_threshold,
        "rrf_k": args.rrf_k,
        "filter_applied_count": filter_applied_count,
        "filter_fallback_count": filter_fallback_count,
        "filter_reasons": filter_reasons,
        }   ,
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

    print("\n===== Metadata Filter Hybrid =====")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(f"filter_applied_count={filter_applied_count}")
    print(f"filter_fallback_count={filter_fallback_count}")
    print(f"filter_reasons={filter_reasons}")
    print(f"failed_ids={report['failed_ids']}")
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

            


