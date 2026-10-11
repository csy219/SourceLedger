import argparse
import json
import time
import sys
from pathlib import Path
from typing import Any

import chromadb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pdf_rag import embed
from run_fixed_chunk_baseline import build_summary, expected_ranks
from S06_2_parent_child_index import build_parents_and_children
from S08_3_bm25_index import BM25Index
from S09_2_rrf_fusion import fuse_rrf
from S09_3_weighted_fusion import fuse_weighted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 vector、BM25 与 Hybrid 变体评测"
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
        / "S09_4_hybrid_variants.json",
    )
    return parser.parse_args()


def load_collection(
    db_dir: Path,
    collection_name: str,
) -> chromadb.Collection:
    client = chromadb.PersistentClient(path=str(db_dir))
    try:
        return client.get_collection(collection_name)
    except (ValueError, chromadb.errors.NotFoundError) as exc:
        raise RuntimeError(
            f"集合不存在: {collection_name}，请先运行 semantic 模式"
        ) from exc


def query_vector_hits(
    collection: chromadb.Collection,
    question: str,
    candidate_k: int,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    result = collection.query(
        query_embeddings=embed([question]),
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"],
    )
    latency_ms = (time.perf_counter() - started) * 1000

    ids = result.get("ids", [[]])[0]
    hits = []

    for child_id, document, metadata, distance in zip(
        ids,
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        hits.append(
            {
                "child_id": child_id,
                "source": metadata["source"],
                "page": metadata["page"],
                "chunk_index": metadata["chunk_index"],
                "distance": round(float(distance), 4),
                "text": document,
            }
        )

    return hits, latency_ms


def evaluate_variant(
    case: dict[str, Any],
    hits: list[dict[str, Any]],
    latency_ms: float,
    vector_hits: list[dict[str, Any]],
    metric_k: int,
    distance_threshold: float,
) -> dict[str, Any]:
    ranks = expected_ranks(
        hits=hits[:metric_k],
        expected_sources=case["expected_sources"],
    )
    source_check = case["source_check"]

    if source_check == "none":
        if "injection" in case["category"]:
            retrieval_ok = True
        else:
            retrieval_ok = not [
                hit for hit in vector_hits
                if hit["distance"] < distance_threshold
            ]
    elif source_check == "any":
        retrieval_ok = any(rank is not None for rank in ranks)
    elif source_check == "all":
        retrieval_ok = bool(ranks) and all(
            rank is not None for rank in ranks
        )
    else:
        raise ValueError(
            f"{case['id']}: 未知 source_check={source_check}"
        )

    reciprocal_rank = 0.0
    found_ranks = [rank for rank in ranks if rank is not None]
    if found_ranks:
        reciprocal_rank = 1.0 / min(found_ranks)

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
                "child_id": hit.get("child_id", ""),
                "distance": hit.get("distance"),
                "score": hit.get("score"),
                "hybrid_score": hit.get("hybrid_score"),
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
    collection = load_collection(args.db, args.collection)

    _, children = build_parents_and_children(
        corpus_dir=args.corpus,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        semantic_threshold=args.semantic_threshold,
    )
    bm25_index = BM25Index()
    bm25_index.fit(children)

    variant_rows: dict[str, list[dict[str, Any]]] = {
        "vector": [],
        "bm25": [],
        "rrf": [],
        "weighted_0_7": [],
        "weighted_0_5": [],
    }

    for case in cases:
        vector_hits, vector_latency = query_vector_hits(
            collection=collection,
            question=case["question"],
            candidate_k=args.candidate_k,
        )

        bm25_started = time.perf_counter()
        bm25_hits = bm25_index.search(
            query=case["question"],
            top_k=args.candidate_k,
        )
        bm25_latency = (
            time.perf_counter() - bm25_started
        ) * 1000

        rrf_hits = fuse_rrf(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            k=args.rrf_k,
            top_k=args.candidate_k,
        )
        weighted_0_7_hits = fuse_weighted(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            vector_weight=0.7,
            bm25_weight=0.3,
            top_k=args.candidate_k,
        )
        weighted_0_5_hits = fuse_weighted(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            vector_weight=0.5,
            bm25_weight=0.5,
            top_k=args.candidate_k,
        )

        hybrid_latency = vector_latency + bm25_latency
        variants = {
            "vector": (vector_hits, vector_latency),
            "bm25": (bm25_hits, bm25_latency),
            "rrf": (rrf_hits, hybrid_latency),
            "weighted_0_7": (
                weighted_0_7_hits,
                hybrid_latency,
            ),
            "weighted_0_5": (
                weighted_0_5_hits,
                hybrid_latency,
            ),
        }

        for variant_name, (hits, latency) in variants.items():
            variant_rows[variant_name].append(
                evaluate_variant(
                    case=case,
                    hits=hits,
                    latency_ms=latency,
                    vector_hits=vector_hits,
                    metric_k=args.metric_k,
                    distance_threshold=args.distance_threshold,
                )
            )

    report = {
        "config": {
            "candidate_k": args.candidate_k,
            "metric_k": args.metric_k,
            "distance_threshold": args.distance_threshold,
            "rrf_k": args.rrf_k,
            "document_count": len(children),
        },
        "variants": {},
    }

    for variant_name, rows in variant_rows.items():
        summary = build_summary(rows, args.metric_k)
        report["variants"][variant_name] = {
            "summary": summary,
            "failed_ids": [
                row["id"]
                for row in rows
                if not row["retrieval_ok"]
            ],
            "rows": rows,
        }

        print(f"\n===== {variant_name} =====")
        for key, value in summary.items():
            print(f"{key}: {value}")
        print(
            "failed_ids:",
            report["variants"][variant_name]["failed_ids"],
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nreport: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
