import argparse
import json
import time
from pathlib import Path
from typing import Any

from S06_2_parent_child_index import build_parents_and_children
from S08_3_bm25_index import BM25Index
from run_fixed_chunk_baseline import build_summary,expected_ranks

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行纯 BM25 检索 baseline"
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
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--overlap", type=int, default=80)
    parser.add_argument(
        "--semantic-threshold",
        type=float,
        default=0.72,
    )
    parser.add_argument("--candidate-k", type=int, default=10)
    parser.add_argument("--metric-k", type=int, default=4)
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--k1", type=float, default=1.5)
    parser.add_argument("--b", type=float, default=0.75)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent
        / "reports"
        / "S08_4_bm25_baseline.json",
    )
    return parser.parse_args()

def evaluate_case(
    index:BM25Index,
    case:dict[str,Any],
    candidate_k:int,
    metric_k:int,
    score_threshold:float
)->dict[str,Any]:
    start=time.perf_counter()
    hits=index.search(
        query=case["question"],
        top_k=candidate_k
    )

    latency_ms=(time.perf_counter()-start)*1000

    filtered_hits= [
        hit for hit in hits
        if hit["score"]>score_threshold
    ]

    ranks=expected_ranks(
        hits=hits[:metric_k],
        expected_sources=case["expected_sources"]
    )

    source_check=case["source_check"]

    if source_check =="none":
        if "injection" in case["category"]:
            retrieval_ok=True
        else:
            retrieval_ok=not filtered_hits
    elif source_check=="any":
        retrieval_ok=any(rank is not None for rank in ranks)
    elif source_check=="all":
        retrieval_ok=bool(ranks) and all(rank is not None for rank in ranks)
    else:
        raise ValueError(
            f"{case['id']}: 未找到 source_check={source_check}"
        )

    reciprocal_rank=0.0
    found_ranks=[rank for rank in ranks if rank is not None]
    if found_ranks:
        reciprocal_rank=1.0/min(found_ranks)

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "source_check": source_check,
        "retrieval_ok": retrieval_ok,
        "expected_sources": case["expected_sources"],
        "ranks": ranks,
        "reciprocal_rank": round(reciprocal_rank, 4),
        "latency_ms": round(latency_ms, 2),
        "parent_context": {
            "parent_occurrences": 0,
            "unique_parent_count": 0,
            "context_chars": 0,
            "context_tokens_est": 0,
            "parents": [],
        },
        "hits": [
            {
                "source": hit["source"],
                "page": hit["page"],
                "child_id": hit["child_id"],
                "score": hit["score"],
            }
            for hit in hits
        ],
    }

def main() -> int:
    args = parse_args()

    document = json.loads(
        args.eval_set.read_text(encoding="utf-8")
    )
    cases = document.get("cases", [])

    _, children = build_parents_and_children(
        corpus_dir=args.corpus,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        semantic_threshold=args.semantic_threshold,
    )

    index = BM25Index(k1=args.k1, b=args.b)
    index.fit(children)

    rows = [
        evaluate_case(
            index=index,
            case=case,
            candidate_k=args.candidate_k,
            metric_k=args.metric_k,
            score_threshold=args.score_threshold,
        )
        for case in cases
    ]

    summary = build_summary(rows, args.metric_k)

    report = {
        "config": {
            "retrieval": "bm25_only",
            "chunk_mode": "semantic",
            "chunk_size": args.chunk_size,
            "overlap": args.overlap,
            "semantic_threshold": args.semantic_threshold,
            "candidate_k": args.candidate_k,
            "metric_k": args.metric_k,
            "score_threshold": args.score_threshold,
            "k1": args.k1,
            "b": args.b,
            "document_count": len(children),
        },
        "summary": summary,
        "rows": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n===== BM25 Baseline =====")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print(
        "failed_ids:",
        [row["id"] for row in rows if not row["retrieval_ok"]],
    )
    print(f"report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())