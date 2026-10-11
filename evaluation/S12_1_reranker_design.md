# S12-1 Reranker 选型与候选池策略

## 目标

在 S11 Metadata Filter Hybrid 后增加 cross-encoder rerank。

流程：

```text
vector top20
BM25 top20
child_id 去重
RRF
candidate top20
cross-encoder rerank
final top4
```

重点观察：

```text
E33 知识手册第 9 页能否从第 5 名进入前 4
Hit@1
MRR
nDCG@4
Recall@4
延迟
```

## 为什么需要 Reranker

向量检索是双塔召回：

```text
问题向量
文档向量
分别编码
```

BM25：

```text
只看词项重叠
```

RRF：

```text
只看排名
不判断内容是否真正回答问题
```

Cross-encoder 会同时输入：

```text
问题
+ child 文本
```

直接输出相关性分数，更适合最终精排。

## 候选池策略

设置：

```text
retrieval_candidate_k=20
metric_k=4
```

原因：

1. E33 正确页当前排第 5；
2. 只对 top4 rerank 无法把第 5 名拉回前 4；
3. top20 给 reranker 足够候选空间；
4. 当前仅有 53 个 child，成本可接受。

RRF 后保留 top20，再交给 reranker。

## Reranker 选型

优先选择：

```text
BAAI/bge-reranker-v2-m3
```

备选：

```text
BAAI/bge-reranker-base
```

如果模型无法下载或加载：

```text
NoOp Reranker
```

NoOp Reranker 保持 RRF 原顺序，不能伪造 rerank。

必须记录：

```text
reranker_backend
reranker_loaded
```

## 模型输入

每个 query-document pair：

```python
question
child["text"]
```

CrossEncoder 输出每条候选的相关性分数。

## Rerank 排序

排序规则：

```text
rerank_score 降序
RRF score 降序
child_id
```

最终取：

```text
metric_k=4
```

## 候选记录字段

```text
child_id
source
page
text
rrf_score
vector_rank
bm25_rank
rerank_score
rrf_rank
rerank_rank
```

用于分析：

- 哪些候选被提升；
- 哪些被降级；
- 正确来源是否进入前 4。

## 初始模型参数

```text
max_length=512
batch_size=8
device=cpu
```

如果使用 GPU，必须记录：

```text
device=cuda
```

模型加载耗时单独记录：

```text
reranker_load_ms
```

单次 rerank 延迟记录：

```text
rerank_latency_ms_avg
```

## 无答案题

保持 S11 规则：

```text
普通无答案题以原始 query 的 vector threshold 为主
```

Reranker 只负责重排已召回候选，不负责拒答。

## 新增指标

```text
nDCG@4
rerank_latency_ms_avg
reranker_load_ms
rerank_changed_top1_count
rerank_promoted_expected_count
rerank_demoted_expected_count
```

## 对照实验

必须比较：

```text
S11 Filtered Hybrid, candidate_k=20, 不 rerank
对比
S12 Rerank, candidate_k=20
```

不能直接和 S09 candidate_k=10 比较，否则同时改变了候选池和 reranker。

## 成功条件

至少满足一个：

1. retrieval_passed 高于 45；
2. E33 通过；
3. Hit@1 或 MRR 高于 S11 k=20 对照；
4. nDCG@4 提高；
5. 延迟仍在可接受范围。

如果没有提升：

```text
保留 reranker 代码，但默认关闭。
```

## 硬边界

1. 不重新分块；
2. 不修改 eval_set；
3. metadata filter 与 S11 一致；
4. 只改变候选池和 rerank；
5. 必须有 k=20 无 rerank 对照；
6. 必须记录模型名称和设备；
7. E33 重点观察，但不能只看 E33；
8. 模型下载失败时必须明确记录，不能伪造结果。

## 下一步

S12-2 实现：

```python
class Reranker:
    def rerank(question, candidates, top_k):
        pass
```
