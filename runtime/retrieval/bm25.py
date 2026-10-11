# 这是 **B03 阶段的 BM25 关键词检索引擎完整实现**，属于混合检索里的「词法检索路」，
# 和 Chroma 向量检索并行运行，输出完全对齐的 `RetrievalCandidate` 结构，供后续 RRF 融合使用。它是纯内存实现，针对中文场景做了分词优化，同时复用了统一的过滤规则。
from __future__ import annotations

# 计算 BM25 公式里的对数、除法运算
import math

# 正则表达式，实现中文 / 英文 / 日期 / 数字的专项分词
import re
import time

# ``词频统计，统计每个词在文档 / 全局出现的次数
from collections import Counter
from typing import Any

from runtime.rag_contracts import RetrievalCandidate, RetrievalFilters
from runtime.retrieval.filters import matches_filters


### 分词正则常量
# 针对中文场景定制的多模式分词规则，解决中文无空格、标识符、日期、数字混合的问题。
CHINESE_PATTERN = re.compile(
    r"[\u4e00-\u9fff]+"
)
IDENTIFIER_PATTERN = re.compile(
    r"[a-zA-Z_][a-zA-Z0-9_.-]*"
)
DATE_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}"
)
NUMBER_PATTERN = re.compile(
    r"\d+(?:\.\d+)?%?"
)
IDENTIFIER_SPLIT_PATTERN = re.compile(
    r"[_.-]+"
)


def tokenize(text:str)->list[str]:
    lower=text.lower()
    tokens:list[str]=[]

    for match in CHINESE_PATTERN.finditer(lower):
        sequence=match.group(0)
        tokens.extend(sequence)
        tokens.extend(
            sequence[index:index+2]
            for index in range(len(sequence) - 1)
        )

    for match in IDENTIFIER_PATTERN.finditer(lower):
        identifier=match.group(0)
        tokens.append(identifier)

        tokens.extend(
            part
            for part in IDENTIFIER_SPLIT_PATTERN.split(identifier)
            if part and part != identifier
        )

    for match in DATE_PATTERN.finditer(lower):
        value=match.group(0)
        tokens.append(value)
        tokens.extend(value.split("-"))

    for match in NUMBER_PATTERN.finditer(lower):
        tokens.append(match.group(0))

    return tokens

class BM25Retriever:
    def __init__(
        self,
        # BM25 经典参数，控制**词频饱和度**。值越高，词频增加对得分的提升越慢。1.5 是通用最优值
        k1:float=1.5,
        # BM25 经典参数，控制**文档长度归一化强度**。0 完全不归一化，1 完全归一化。0.75 是通用最优值
        b:float=0.75,
    )->None:
        self.k1=k1
        self.b=b

        # 索引后的文档库列表，每个文档包含 chunk_id、text、source、page、metadata
        self.documents:list[dict[str,Any]]=[]

        # 每个文档的词频统计（Counter），和 documents 按索引一一对应
        self.term_frequencies:list[Counter[str]]=[]

        # 全局文档频率：每个词在多少个文档里出现过，用于计算 IDF
        self.document_frequency:Counter[str]=Counter()

        # 每个词的**逆文档频率**，词越稀有权重越高，预计算好提升搜索速度
        self.idf:dict[str,float]={}
        # 每个文档的词条长度，用于长度归一化
        self.document_lengths:list[int]=[]
        # 全文档平均长度，BM25 公式的基准值
        self.average_document_length=0.0

    # 2. `fit_documents` 加载文档并建索引
    # 设计意图：做格式适配层。不管文档来自哪里（Chroma、本地文件、手动构造），进来后都统一成相同结构，后续逻辑不用关心来源。
    def fit_documents(
        self,
        documents:list[dict[str,Any]],
    )->None:
        self.documents=[]

        for document in documents:
            metadata=dict(document.get("metadata") or {})
            source_value=(document.get("source") or metadata.get("source") or ""); source=str(source_value)
            page=int(document.get("page") or metadata.get("page") or 0)
            chunk_id = str(
                document.get("chunk_id")
                or document.get("child_id")
                or ""
            )

            if not chunk_id or not source:
                continue

            metadata["source"] = source
            metadata["page"] = page

            self.documents.append(
                {
                    "chunk_id": chunk_id,
                    "text": str(
                        document["text"]
                    ),
                    "source": source,
                    "page": page,
                    "metadata": metadata,
                }
            )
        # 调用 `_build_index()` 正式构建倒排索引和统计量
        self._build_index()

    # 3. `fit_collection` 从 Chroma 集合加载
    #     - 输入：Chroma 集合对象
    # - 作用：直接从 Chroma 拉取全部文档，转换成标准格式后调用 `fit_documents` 建索引
    # #### 核心逻辑
    # 1. 调用 Chroma 的 `get` 接口，批量获取所有文档 ID、文本、元数据
    # 2. 按索引一一对应，组装成 `{chunk_id, text, metadata}` 格式
    # 3. 空文本直接跳过
    # 4. 传给 `fit_documents` 统一处理
    # > 设计意图：**BM25 和向量检索共用同一份语料**，不用单独维护两份数据，保证两边检索的文档池完全一致，后续融合公平。
    def fit_collection(self,collection:Any)->None:
        result=collection.get(
            include=["documents","metadatas"]
        )
        ids=result.get("ids") or []
        texts=result.get("documents") or []
        metadatas=result.get("metadatas") or []

        documents:list[dict[str,Any]]=[]
        for chunk_id,text,metadata in zip(
            ids,
            texts,
            metadatas,
        ):
            if not text:
                continue

            documents.append(
                {
                    "chunk_id":str(chunk_id),
                    "text":str(text),
                    "metadata":dict(metadata or {}),
                },
            )
        self.fit_documents(documents)

    # 4. `_build_index` 内部构建索引
    def _build_index(self)->None:
        # 初始化统计容器
        self.term_frequencies=[]
        self.document_frequency=Counter()
        self.document_lengths=[]

        # 遍历文档，统计词频
        for document in self.documents:
            tokens=tokenize(document["text"])
            # `frequencies = Counter(tokens)`：当前文档里，每个 term 出现多少次（TF
            frequencies=Counter(tokens)
            self.term_frequencies.append(frequencies)
            self.document_lengths.append(len(tokens))

            # 全局统计每个词在多少文档里出现（文档频率 DF）
            for term in frequencies:
                self.document_frequency[term]+=1

            # 空库边界处理
        count=len(self.documents)
        if count==0:
            self.average_document_length=0.0
            self.idf={}
            return
        # 计算平均文档长度
        self.average_document_length=sum(self.document_lengths)/count

        # 计算每个词的 IDF（逆文档频率）
        # - 使用带平滑的 BM25 经典 IDF 公式
        # - 含义：一个词在越少文档里出现，IDF 值越高，检索时权重越大
        # - 预计算好存在字典里，搜索时直接查表，不用重复计算
        self.idf={
            term:math.log(
                1.0 + (count - frequency + 0.5) / (frequency + 0.5)
            )
            for term,frequency in self.document_frequency.items()
        }
    # 5. `_score` 单文档 BM25 评分
    # - 输入：查询词条列表、文档索引
    # - 输出：该文档和查询的 BM25 相似度得分
    # - 实现：标准 **BM25 Okapi** 评分公式
    def _score(
        self,
        query_terms:list[str],
        index:int,
    )->float:
        # 空库直接返回 0
        if self.average_document_length==0:
            return 0.0

        #单文档的词频 TF
        frequencies=self.term_frequencies[index]
        #单文档里的key的长度
        length=self.document_lengths[index]
        score=0.0

        # 遍历查询词，累加得分
        for term in query_terms:
            frequency=frequencies.get(term,0)
            if frequency==0:
                continue

            # 标准 BM25 公式拆解：

            # - `idf`：逆文档频率权重，词越稀有贡献越大
            # - `frequency * (k1 + 1) / denominator`：词频饱和度因子，词频越高贡献越大，但增长会逐渐饱和
            # - 分母里的 `length / average_document_length`：文档长度归一化，抑制长文档天然词多的优势
            idf = self.idf.get(term, 0.0)

            denominator=(
                frequency
                +self.k1
                *(
                    1.0
                    -self.b
                    +self.b
                    * length
                    / self.average_document_length
                )
            )

            #对**单个词项 term** 的得分：
            #(score_{term} = IDF(term) \times \frac{freq \cdot (k_1+1)}{freq + k_1 \cdot \big(1-b + b \cdot \frac{dl}{avgdl}\big)}\)
            score+=(
                idf
                * frequency
                * (self.k1 + 1.0)
                / denominator
            )
        return score
        
    # 6. `search` 对外搜索接口
    # 参数	用途
    # query	查询字符串，一般传 B02 输出的 keyword_query
    # filters	标准过滤契约，和向量检索用同一套
    # top_k	返回前 K 个结果
    # 返回值	（候选列表，耗时毫秒）
    def search(
        self,
        query:str,
        filters:RetrievalFilters,
        top_k:int=20,
    )->tuple[list[RetrievalCandidate],float]:
        started=time.perf_counter()
        query_terms=tokenize(query)
        scored:list[tuple[float,int]]=[]

        # 遍历文档：先过滤，再评分
        # - **过滤前置**：先调用共享的 `matches_filters` 做条件过滤，不符合的直接跳过，不计算得分，提升性能
        # - 得分大于 0 才保留，完全不相关的文档排除
        for index,document in enumerate(self.documents):
            if not matches_filters(
                source=document["source"],
                page=document["page"],
                metadata=document["metadata"],
                filters=filters,
            ):
                continue
            score=self._score(query_terms,index)

            if score>0:
                scored.append((score,index))

        # - 主排序：按得分**降序**，分越高越靠前
        # - 次排序：得分相同时按 `chunk_id` 升序，保证排序稳定可复现
        scored.sort(
            key=lambda item:(
                -item[0],
                self.documents[item[1]]["chunk_id"],
            )
        )

        # 组装标准候选对象
        # - 取 top_k 个结果，从 1 开始排名
        # - 转换成标准的 `RetrievalCandidate` 契约
        # - 只填充 `bm25_rank` 和 `bm25_score` 字段，向量相关字段留空，和向量检索输出结构完全对齐
        # - 得分保留 6 位小数，避免精度冗余
        candidates:list[RetrievalCandidate]=[]

        for rank,(score,index) in enumerate(scored[:top_k],start=1):
            document=self.documents[index]
            candidates.append(
                RetrievalCandidate(
                    chunk_id=document[
                        "chunk_id"
                    ],
                    text=document["text"],
                    source=document[
                        "source"
                    ],
                    page=document["page"],
                    bm25_rank=rank,
                    bm25_score=round(
                        score,
                        6,
                    ),
                    metadata=dict(
                        document["metadata"]
                    ),
                )
            )

        latency_ms = (
            time.perf_counter() - started
        ) * 1000

        return (
            candidates,
            round(latency_ms, 2),
        )


## 整体设计总结

# 1. **输出对齐**：输出和向量检索完全相同的 `RetrievalCandidate` 结构，后续 RRF 融合模块不用做格式转换，直接两路合并
# 2. **过滤统一**：复用共享的 `matches_filters` 函数，和向量检索使用完全相同的过滤规则，保证两路检索的文档池一致
# 3. **中文优化**：定制的字粒度 + 二元组分词策略，比通用英文分词器更适合中文企业知识库场景
# 4. **性能优化**：索引预计算、过滤前置、IDF 查表，纯内存检索速度极快
# 5. **语料共用**：支持直接从 Chroma 集合加载文档，两路检索共用同一份语料，避免数据不一致

# B02 输出 keyword_query → BM25Retriever.search() → bm25_candidates
#                                                           ↘
#                                                           RRF 融合 → 后续重排/上下文
#                                                           ↗
# B02 输出 semantic_query → Chroma 向量检索 → vector_candidates


            

            

    

    

        
        


