# 这段代码实现了 **RRF（Reciprocal Rank Fusion，倒数排名融合）** 算法，是混合检索（Hybrid Search）场景下的经典结果融合方案。
# 它的核心作用是：将**向量检索（密集检索）**和**BM25 关键词检索（稀疏检索）**两路不同维度的检索结果，通过「排名倒数求和」的方式计算综合得分，最终输出融合重排序后的 Top-K 结果。
# RRF 的优势在于**不依赖两路检索的原始分数（量纲、分布差异大）**，仅通过排名计算得分，鲁棒性极强，广泛用于 RAG 检索增强生成系统中。
import math
from typing import Any

def fuse_rrf(
    vector_hits:list[dict[str,Any]],
    bm25_hits:list[dict[str,Any]],
    # RRF 平滑系数:K
    k:int=60,
    top_k:int=10,
)->list[dict[str,Any]]:
    fused:dict[str,dict[str,Any]]={}
    for rank,hit in enumerate(vector_hits,start=1):
        child_id=hit["child_id"]
        item=fused.setdefault(
            child_id,
            {
                "child_id":child_id,
                "source":hit["source"],
                "page":hit["page"],
                "text":hit["text"],
                "vector_rank":None,
                "bm25_rank":None,
                "vector_distance":None,
                "bm25_score":None,
                "rrf_score":0.0,
            },
        )
        item["vector_rank"]=rank
        item["vector_distance"]=hit.get("distance")
        item["rrf_score"]+=1.0/(k+rank)

    for rank, hit in enumerate(bm25_hits, start=1):
        child_id = hit["child_id"]
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
                "bm25_score": None,
                "rrf_score": 0.0,
            },
        )
        item["bm25_rank"]=rank
        item["bm25_score"]=hit.get("score")
        item["rrf_score"]+=1.0/(k+rank)

    ordered=sorted(
        # 待排序对象：所有融合后的文档字典
        fused.values(),
        key=lambda item:(
            # 第1优先级：RRF 综合得分
            -item["rrf_score"],
            # 第2优先级：向量检索排名（无排名则用无穷大兜底）
            item["vector_rank"]
            if item["vector_rank"] is not None
            else math.inf,
            item["bm25_rank"]
            if item["bm25_rank"] is not None
            else math.inf,
            item["child_id"]
        ),
    )

    for rank,item in enumerate(ordered[:top_k],start=1):
        item["rank"]=rank
        item["rrf_score"]=round(item["rrf_score"],8)

    return ordered[:top_k]

def main()->int:
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

    for hit in fuse_rrf(vector_hits, bm25_hits):
        print(
            f"rank={hit['rank']} "
            f"child_id={hit['child_id']} "
            f"vector_rank={hit['vector_rank']} "
            f"bm25_rank={hit['bm25_rank']} "
            f"rrf={hit['rrf_score']}"
        )
    return 0
if __name__ == "__main__":
    raise SystemExit(main())