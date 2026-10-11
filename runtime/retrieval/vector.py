"""Vector retrieval over the Chroma collection."""

from __future__ import annotations

import time
from typing import Any, Callable

from runtime.rag_contracts import (
    RetrievalCandidate,
    RetrievalFilters,
)
from runtime.retrieval.filters import (
    build_chroma_where,
)


Embedder = Callable[
    [list[str]],
    list[list[float]],
]


class VectorRetriever:
    def __init__(
        self,
        collection:Any | None=None,
        embedder:Embedder | None=None,
    ):
        if collection is None:
            from pdf_rag import get_collection

            collection=get_collection()

        if embedder is None:
            from pdf_rag import embed
            embedder=embed

        self.collection=collection
        self.embedder=embedder


    def search(
        self,
        query,
        filters:RetrievalFilters,
        top_k:int=20,
    )->tuple[list[RetrievalCandidate],float]:
        started = time.perf_counter()

        # - 空查询、空库直接快速返回空结果，不执行无效计算
        # - 边界处理前置，保证异常场景下耗时统计也准确
        if not query.strip():
            return ([], round((time.perf_counter() - started) * 1000, 2))

        count = int(self.collection.count())
        if count <= 0:
            return ([], round((time.perf_counter() - started) * 1000, 2))

        # ② 计算实际返回数量
        n_results=max(1,min(top_k,count))

        # ③ 构造查询参数
        # 参数项	用途
        # query_embeddings	查询的向量表示。调用嵌入函数把文本转成向量，传入列表格式对应 Chroma 批量查询接口
        # n_results	返回结果数量
        # include	指定返回字段：
        # • documents：文档文本
        # • metadatas：元数据
        # • distances：向量距离（相似度的反向）
        query_kwargs:dict[str,Any]={
            "query_embeddings":self.embedder([query]),
            "n_results":n_results,
            "include":["documents","metadatas","distances"],
        }
        # ④ 组装过滤条件
        # - 调用共享的过滤转换函数，把标准 `RetrievalFilters` 转换成 Chroma 原生 `$and`/`$in`/`$eq` 语法
        # - 有过滤条件就加入查询参数，没有就不加，实现数据库层面下推过滤
        where=build_chroma_where(filters=filters)
        if where is not None:
            query_kwargs["where"]=where

        # ⑤ 执行向量检索
        # - 调用 Chroma 原生查询接口，**数据库内部同时完成「向量相似度计算 + 元数据过滤」**
        # - 这是向量检索性能优势的核心：过滤和检索一次完成，不用拉回全部数据再处理
        result=self.collection.query(**query_kwargs)

        # - Chroma 支持批量查询，所以返回结果都是二维数组（第一维对应第几个查询）
        # - 我们只查一个 query，所以取索引 `[0]` 对应的结果，拆成四个平行列表
        ids_group = result.get("ids") or [[]]
        documents_group = result.get("documents") or [[]]
        metadata_group = result.get("metadatas") or [[]]
        distance_group = result.get("distances") or [[]]

        ids = ids_group[0]
        documents = documents_group[0]
        metadatas = metadata_group[0]
        distances = distance_group[0]

        # ⑦ 遍历组装标准候选对象
        # - `rank`：从 1 开始的排名，对应 `vector_rank` 字段
        # - 跳过空文本、缺少 source 的无效数据
        # - 从元数据提取 `source`、`page`，并回写到 metadata 中，保证和 BM25 输出的元数据结构完全一致
        # - **关键转换**：`vector_score = 1.0 - distance`
        # - Chroma 返回的 `distance` 是余弦距离，值越小越相似（0 最相似，最大 2）
        # - 转换成相似度分数，值越大越相似，**和 BM25 得分趋势对齐**，方便后续 RRF 融合
        # - 保留 6 位小数，和 BM25 精度一致
        # - 只填充 `vector_rank` / `vector_score`，BM25 相关字段留空，和 BM25 输出结构完全对称
        candidates: list[RetrievalCandidate] = []
        for rank, (chunk_id, text, raw_metadata, distance) in enumerate(
            zip(ids, documents, metadatas, distances),
            start=1,
        ):
            if not text:
                continue
            metadata = dict(raw_metadata or {})
            source = str(metadata.get("source", ""))
            if not source:
                continue
            page = int(metadata.get("page", 0) or 0)
            
            metadata["source"] = source
            metadata["page"] = page
            
            candidates.append(
                RetrievalCandidate(
                    chunk_id=str(chunk_id),
                    text=str(text),
                    source=source,
                    page=page,
                    vector_rank=rank,
                    vector_score=round(1.0 - float(distance), 6),
                    metadata=metadata,
                )
            )
        latency_ms = (time.perf_counter() - started) * 1000
        return (candidates, round(latency_ms, 2))


## 四、设计要点总结

### 1. 双路完全对齐
# 对齐维度	说明
# 方法签名	search(query, filters, top_k) 完全一致
# 输入过滤	共用同一套 RetrievalFilters 契约
# 输出结构	都是 RetrievalCandidate，分别填充对应路的排名 / 分数
# 分数趋势	都是「值越大越相关」，向量路做了距离转相似度
# 元数据结构	都统一回写 source、page 到 metadata
# > 好处：后续 RRF 融合、重排、上下文组装模块，不用区分两路结果，统一处理即可。

# ### 2. 边界与鲁棒性

# - 空查询、空库快速返回
# - 无效数据（空文本、无来源）自动跳过
# - 所有字段做类型强转，避免 Chroma 返回类型不一致导致报错

# ### 3. 解耦与兼容

# - 嵌入函数、集合对象都支持注入，方便测试和替换
# - 默认复用旧基线的向量库和嵌入模型，不用重复建设
# - 依赖延迟导入，不强制依赖旧模块

### 在整条链路中的位置

# B02 输出 semantic_query → VectorRetriever.search() → vector_candidates
#                                                           ↘
#                                                           RRF 融合
#                                                           ↗
# B02 输出 keyword_query  → BM25Retriever.search()  → bm25_candidates

