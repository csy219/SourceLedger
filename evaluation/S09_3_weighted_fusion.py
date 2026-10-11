# 这是**加权线性融合（Weighted Score Fusion）** 算法，和你之前写的 RRF 是**两种并列的主流混合检索融合方案**，解决的是同一个问题：怎么把「向量语义检索」和「BM25 关键词检索」两路结果合并成一个更优的排序。
# 简单概括区别：
# - 之前的 RRF：**只看排名投票**，不关心原始分数高低
# - 这个加权融合：**按分数加权算总分**，可以手动调整两路检索的权重占比

import math
from typing import Any

# 这是一个**BM25 分数最小 - 最大归一化（Min-Max Normalization）工具函数**，专门服务于后面的加权融合算法。
# 它的核心作用是：把 BM25 关键词检索的原始分数（取值范围任意，比如 5~9 分、几十上百分），**线性缩放到 [0, 1] 区间**，让它和向量相似度（天然 0~1 区间）量纲统一，之后才能进行加权求和。
def normalize_bm25_scores(
    hits:list[dict[str,Any]],
)->dict[str,Any]:
    scores={
        hit["child_id"]:float(hit.get("score",0.0))
        for hit in hits
    }

    if not scores:
        return {}

    minimum=min(scores.values())
    maximum=max(scores.values())

    # 如果所有文档的 BM25 分数完全相同，那么 `max - min = 0`，直接套用归一化公式会触发 `ZeroDivisionError` 除以零错误。
    # - 处理方式：所有文档的归一化分数统一返回 0.0
    # - 逻辑：既然所有文档分数都一样，说明区分度为 0，统一设为区间最小值 0 是合理的，不影响排序
    if maximum==minimum:
        return{
            child_id:0.0
            for child_id in scores
        }

    return {
        child_id: (score-minimum) / (maximum-minimum)
        for child_id,score in scores.items()
    }

def fuse_weighted(
    vector_hits,
    bm25_hits,
    vector_weight:float=0.7,
    bm25_weight:float=0.3,
    top_k:int=10,
)->list[dict[str,Any]]:
    fused:dict[str,dict[str,Any]]={}
    normalized_bm25=normalize_bm25_scores(bm25_hits)

    for rank, hit in enumerate(vector_hits, start=1):
        child_id = hit["child_id"]
        distance = float(hit.get("distance", 1.0))
        vector_similarity = max(0.0, 1.0 - distance)

        item = fused.setdefault(
            child_id,
            {
                "child_id": child_id,
                "source": hit["source"],
                "page": hit["page"],
                "text": hit.get("text", ""),
                "vector_rank": None,
                "bm25_rank": None,
                "vector_distance": None,
                "vector_similarity": 0.0,
                "bm25_score": None,
                "bm25_normalized": 0.0,
                "hybrid_score": 0.0,
            },
        )
        item["vector_rank"]=rank
        item["vector_distance"]=distance
        item["vector_similarity"]=vector_similarity
        item["hybrid_score"]+=vector_weight*vector_similarity

    for rank,hit in enumerate(bm25_hits,start=1):
        child_id=hit["child_id"]
        bm25_score=float(hit.get("score",0.0))
        bm25_normalized=normalized_bm25.get(child_id,0.0)

        item = fused.setdefault(
            child_id,
            {
                "child_id": child_id,
                "source": hit["source"],
                "page": hit["page"],
                "text": hit.get("text", ""),
                "vector_rank": None,
                "bm25_rank": None,
                "vector_distance": None,
                "vector_similarity": 0.0,
                "bm25_score": None,
                "bm25_normalized": 0.0,
                "hybrid_score": 0.0,
            },
        )
        item["bm25_rank"]=rank
        item["bm25_score"]=bm25_score
        item["bm25_normalized"]=bm25_normalized
        item["hybrid_score"]+=bm25_weight*bm25_normalized

    ordered = sorted(
        fused.values(),
        key=lambda item: (
            -item["hybrid_score"],
            item["vector_rank"]
            if item["vector_rank"] is not None
            else math.inf,
            item["bm25_rank"]
            if item["bm25_rank"] is not None
            else math.inf,
            item["child_id"],
        ),
    )

    for rank, item in enumerate(ordered[:top_k], start=1):
        item["rank"] = rank
        item["vector_similarity"] = round(
            item["vector_similarity"],
            6,
        )
        item["bm25_normalized"] = round(
            item["bm25_normalized"],
            6,
        )
        item["hybrid_score"] = round(item["hybrid_score"], 6)

    return ordered[:top_k]

def main() -> int:
    vector_hits = [
        {
            "child_id": "a",
            "source": "doc.pdf",
            "page": 1,
            "distance": 0.20,
            "text": "A",
        },
        {
            "child_id": "b",
            "source": "doc.pdf",
            "page": 2,
            "distance": 0.30,
            "text": "B",
        },
        {
            "child_id": "c",
            "source": "doc.pdf",
            "page": 3,
            "distance": 0.40,
            "text": "C",
        },
    ]
    bm25_hits = [
        {
            "child_id": "b",
            "source": "doc.pdf",
            "page": 2,
            "score": 9.0,
            "text": "B",
        },
        {
            "child_id": "d",
            "source": "doc.pdf",
            "page": 4,
            "score": 7.0,
            "text": "D",
        },
        {
            "child_id": "a",
            "source": "doc.pdf",
            "page": 1,
            "score": 5.0,
            "text": "A",
        },
    ]

    for hit in fuse_weighted(
        vector_hits=vector_hits,
        bm25_hits=bm25_hits,
        vector_weight=0.7,
        bm25_weight=0.3
    ):
        print(
            f"rank={hit['rank']} "
            f"child_id={hit['child_id']} "
            f"vector_sim={hit['vector_similarity']} "
            f"bm25_norm={hit['bm25_normalized']} "
            f"hybrid={hit['hybrid_score']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

