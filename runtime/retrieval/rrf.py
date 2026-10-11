# 这是 **B04 阶段的核心算法：RRF（Reciprocal Rank Fusion，倒数排名融合）**，是混合检索的灵魂环节。它解决了「向量得分和 BM25 分数尺度完全不同，无法直接加权相加」的问题，只基于**排名位置**来融合两路结果，是信息检索领域经典的无偏融合算法。

# 融合后的结果会保留两路所有原始排名 / 分数，同时新增融合后的排名和得分，输出标准的 `RetrievalCandidate` 列表，直接对接后续重排和上下文组装。

"""Reciprocal Rank Fusion for Vector and BM25."""

from __future__ import annotations

import time
from typing import Any

from runtime.rag_contracts import (
    RetrievalCandidate,
)

# 参数	含义
# rank	文档在某一路的排名，从 1 开始
# weight	该路检索的权重
# k	平滑系数，默认 60，业界通用经验值
# **计算逻辑**：

# - 排名越靠前（rank 越小），贡献值越大，符合直觉
# - k 越大，排名靠后的文档贡献下降越平缓；k 越小，头部文档的优势越大
# - 举例：k=60、权重 = 1 时，第 1 名贡献 1/61 ≈ 0.0164，第 2 名贡献 1/62 ≈ 0.0161，衰减非常平缓
def _rank_contribution(
    rank:int,
    weight:float,
    k:int,
)->float:
    return weight/(k+rank)


def fuse_rrf(
    vector_candidates: (
        list[RetrievalCandidate]
        | tuple[RetrievalCandidate, ...]
    ),
    bm25_candidates: (
        list[RetrievalCandidate]
        | tuple[RetrievalCandidate, ...]
    ),
    k: int = 60,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
    top_k: int | None = None,
) -> tuple[
    list[RetrievalCandidate],
    float,
]:
    if k < 0:
        raise ValueError("k cannot be negative")

    if vector_weight < 0:
        raise ValueError(
            "vector_weight cannot be negative"
        )

    if bm25_weight < 0:
        raise ValueError(
            "bm25_weight cannot be negative"
        )

    started = time.perf_counter()
    merged:dict[str,dict[str,Any]]={}

    ##### ③ `add_candidate` 内部合并函数
    # 这是融合的核心逻辑，处理单个候选文档，把它的信息和贡献分合并到 `merged` 中
    def add_candidate(
        candidate:RetrievalCandidate,
        source:str,
        weight:float,
    )->None:
        chunk_id=candidate.chunk_id.strip()

        if not chunk_id:
            return

        entry = merged.setdefault(
            chunk_id,
            {
                "chunk_id": chunk_id,
                "text": candidate.text,
                "source": candidate.source,
                "page": candidate.page,
                "metadata": {},
                "vector_rank": None,
                "vector_score": None,
                "bm25_rank": None,
                "bm25_score": None,
                "rrf_score": 0.0,
            },
        )

        entry["metadata"].update(
            candidate.metadata
        )

        if not entry["text"]:
            entry["text"] = candidate.text

        if not entry["source"]:
            entry["source"] = (
                candidate.source
            )

        if not entry["page"]:
            entry["page"] = candidate.page

        if source == "vector":
            rank = candidate.vector_rank

            if rank is None:
                return

            entry["vector_rank"] = rank
            entry["vector_score"] = (
                candidate.vector_score
            )
            entry["rrf_score"] += (
                _rank_contribution(
                    rank=rank,
                    weight=vector_weight,
                    k=k,
                )
            )
            return

        rank = candidate.bm25_rank

        if rank is None:
            return

        entry["bm25_rank"] = rank
        entry["bm25_score"] = (
            candidate.bm25_score
        )
        entry["rrf_score"] += (
            _rank_contribution(
                rank=rank,
                weight=bm25_weight,
                k=k,
            )
        )
    for candidate in vector_candidates:
        add_candidate(
            candidate,
            source="vector",
            weight=vector_weight,
        )

    for candidate in bm25_candidates:
        add_candidate(
            candidate,
            source="bm25",
            weight=bm25_weight,
        )

    entries = list(merged.values())

    entries.sort(
        key=lambda item: (
            -float(item["rrf_score"]),
            str(item["chunk_id"]),
        )
    )

    if top_k is not None:
        entries = entries[:top_k]

    results: list[
        RetrievalCandidate
    ] = []

    for rank, entry in enumerate(
        entries,
        start=1,
    ):
        results.append(
            RetrievalCandidate(
                chunk_id=str(
                    entry["chunk_id"]
                ),
                text=str(entry["text"]),
                source=str(
                    entry["source"]
                ),
                page=int(entry["page"]),
                vector_rank=entry[
                    "vector_rank"
                ],
                vector_score=entry[
                    "vector_score"
                ],
                bm25_rank=entry[
                    "bm25_rank"
                ],
                bm25_score=entry[
                    "bm25_score"
                ],
                rrf_rank=rank,
                rrf_score=round(
                    float(
                        entry["rrf_score"]
                    ),
                    8,
                ),
                metadata=dict(
                    entry["metadata"]
                ),
            )
        )

    latency_ms = (
        time.perf_counter() - started
    ) * 1000

    return (
        results,
        round(latency_ms, 2),
    )

# ## 三、举个直观的融合例子

# 假设：

# - 向量路排名：文档 A 第 1 名，文档 B 第 3 名
# - BM25 路排名：文档 A 第 2 名，文档 B 第 1 名
# - k=60，两路权重都是 1.0

# 计算：

# - 文档 A：1/(60+1) + 1/(60+2) ≈ 0.0164 + 0.0161 = **0.0325**
# - 文档 B：1/(60+3) + 1/(60+1) ≈ 0.0159 + 0.0164 = **0.0323**

# 最终融合排名：**A 第 1，B 第 2**
# → 两路都排在头部的文档，融合后总得分更高。

# ---

# ## 四、核心设计特点

# 1. **排名融合，鲁棒性强**：不依赖原始分数的尺度，解决两路分量纲不一致的问题，是业界混合检索的标准方案。
# 2. **全链路信息不丢失**：融合后依然保留每一路的原始排名和分数，方便效果对比、问题排查。
# 3. **权重可调**：支持独立调整两路权重，方便后续 AB 测试优化检索效果。
# 4. **自动去重合并**：同一文档在两路都出现时自动合并，贡献累加，不会重复出现在结果里。
# 5. **稳定排序**：同分按 chunk_id 排序，结果可复现，便于测试和回归。

# ---

# ## 五、在整条链路中的位置

# ```
# B03 并行检索输出
# vector_candidates / bm25_candidates
#           ↓
#     RRF 融合（fuse_rrf）
#           ↓
# fused_candidates（带 rrf_rank/rrf_score）
#           ↓
#     B05 重排（可选触发）
#           ↓
#     B06 上下文组装
# ```

# 融合后的结果会填入 `RetrievalResult.fused_candidates` 字段，和原始两路结果并列保存。
