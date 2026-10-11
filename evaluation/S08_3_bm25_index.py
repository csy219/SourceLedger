import math
from collections import Counter
from typing import Any

from S08_2_tokenizer import tokenize,tokenize_query


class BM25Index:
    # 1. 初始化 `__init__`
    def __init__(
        self,
        k1:float=1.5,
        b:float=0.75
    )->None:
        self.k1=k1
        self.b=b
        self.documents:list[dict[str,Any]]=[]
        self.term_frequencies:list[Counter[str]]=[]
        self.document_frequency:Counter[str]=Counter()
        self.idf:dict[str,float]={}
        self.document_lengths:list[int]=[]
        self.average_document_length=0.0

# 2. `fit()` 构建索引：数据一步步更新
    def fit(
        self,
        documents:list[dict[str,Any]],
    )->None:
        self.documents=documents
        self.term_frequencies=[]
        self.document_frequency=Counter()
        self.document_lengths=[]

        for document in documents:
            tokens=tokenize(document["text"]) # 1. 分词
            frequencies=Counter(tokens) # 2. 统计词频

            self.term_frequencies.append(frequencies) # 3. 存入词频列表
            self.document_lengths.append(len(tokens)) # 4. 存入文档长度

            for term in frequencies: 
                self.document_frequency[term]+=1 # 5. 更新文档频率DF

        document_count=len(documents)

        if document_count==0:
            self.average_document_length=0.0
            self.idf={}
            return

        self.average_document_length=(
            sum(self.document_lengths) / document_count
        )

        # idf = ln(1 + (N - df + 0.5) / (df + 0.5))
        # IDF 体现词的区分度：越罕见的词 IDF 越高。这里所有词都只出现在 1 篇文档里，所以 IDF 全部相同。
        self.idf={
            term: math.log(
                1.0
                +(
                    document_count
                    - frequency
                    + 0.5
                )
                / (frequency + 0.5)
            )
            for term,frequency in self.document_frequency.items()
        }

    # 3. `score_document()` 打分：数值一步步算
    def score_document(
        self,
        query_terms:list[str],
        document_index:int,
    )->float:
        frequencies=self.term_frequencies[document_index]
        document_length=self.document_lengths[document_index]

        if self.average_document_length==0:
            return 0.0

        score=0.0

        for term in query_terms:
            frequency=frequencies.get(term,0)
            if frequency==0:
                continue

            term_idf=self.idf.get(term,0.0)

            # 1 - b = 0.25
            # b * 文档长度 / 平均长度 = 0.75 * 10 / 8.6667 ≈ 0.8654
            # 括号部分 = 0.25 + 0.8654 ≈ 1.1154
            # k1 * 括号 = 1.5 * 1.1154 ≈ 1.6731
            # denominator = 1 + 1.6731 ≈ 2.6731

            denominator=(
                frequency
                + self.k1
                * (
                    1.0
                    -self.b
                    +self.b
                    * document_length
                    / self.average_document_length
                )
            )
            score +=(
                term_idf
                * frequency
                * (self.k1 + 1.0)
                / denominator
            )
        return score
    # 4. `search()` 检索：从打分到结果
    def search(
        self,
        query:str,
        top_k:int=10,
    )->list[dict[str,Any]]:
        query_terms=tokenize_query(query)
        scored:list[tuple[float,int]]=[]

        for document_index in range(len(self.document_lengths)):
            score=self.score_document(query_terms,document_index)
            if score>0:
                scored.append((score,document_index))

        scored.sort(
            key=lambda item:(
                -item[0],
                self.documents[item[1]]["child_id"]
            )
        )

        hits:list[dict[str,Any]]=[]

        for rank,(score,document_index) in enumerate(scored[:top_k],start=1):
            document=self.documents[document_index]
            metadata=document["metadata"]

            hits.append(
                {
                    "rank":rank,
                    "score":round(score,6),
                    "child_id":document["child_id"],
                    "source":metadata["source"],
                    "page":metadata["page"],
                    "chunk_index":metadata["chunk_index"],
                    "parent_id":metadata.get("parent_id",""),
                    "text":document["text"]
                }
            )
        return hits

def main()->int:
    documents = [
        {
            "child_id": "a#p1#c0",
            "text": (
                "每次工具调用写入审计日志："
                "user_id、task_id、tool_name、参数哈希、结果状态"
            ),
            "metadata": {
                "source": "platform.pdf",
                "page": 1,
                "chunk_index": 0,
            },
        },
        {
            "child_id": "a#p2#c0",
            "text": "页面请求 p95 延迟目标为 2 秒以内",
            "metadata": {
                "source": "platform.pdf",
                "page": 2,
                "chunk_index": 0,
            },
        },
        {
            "child_id": "b#p1#c0",
            "text": "API Token 每 90 天轮换一次",
            "metadata": {
                "source": "security.pdf",
                "page": 1,
                "chunk_index": 0,
            },
        },
    ]

    index=BM25Index()
    index.fit(documents)

    for query in [
        "审计日志 user_id task_id",
        "p95 延迟",
        "Token 90 天",
    ]:
        print(f"\nquery:{query}")
        for hit in index.search(query,top_k=3):
            print(
                f"\n{hit['rank']}"
                f"\n{hit['child_id']}"
                f"\nscore={hit['score']}"
                f"{hit['text']}"
            )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())