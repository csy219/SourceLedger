# S09-1 Hybrid Retrieval 融合策略

## 目标

将 vector 与 BM25 的候选结果合并并重新排序，判断是否能产生 complementarity。

固定：

```text
同一 46 条 eval_set
同一 53 个 semantic child
vector candidate_k=10
bm25 candidate_k=10
metric_k=4
```

不重新分块，不修改 child。

## 两路候选

### Vector

字段：

```text
child_id
source
page
distance
vector_rank
```

排序：

```text
distance 越小越相关
```

### BM25

字段：

```text
child_id
source
page
score
bm25_rank
```

排序：

```text
score 越大越相关
```

## 候选合并

以 `child_id` 为唯一键：

```text
vector top10
+ BM25 top10
→ 按 child_id 去重
→ 保留 vector_rank、bm25_rank 和原始分数
```

一个 child 可能：

1. 只在 vector 中出现；
2. 只在 BM25 中出现；
3. 同时出现在两路中。

## 融合策略一：RRF

RRF 全称：

```text
Reciprocal Rank Fusion
倒数排名融合
```

公式：

```text
rrf_score(document)
= sum(
    1 / (k + rank)
)
```

初始：

```text
k=60
```

如果文档在 vector 中排第 1、BM25 中排第 4：

```text
1 / (60 + 1) + 1 / (60 + 4)
```

如果只在一路出现，只计算存在的那一路。

优点：

- 不需要统一 distance 和 BM25 score 的量纲；
- 对外部分数范围更稳健；
- 实现简单，适合作为第一版 Hybrid。

## 融合策略二：加权分数融合

### Vector similarity

Chroma 返回的是 cosine distance：

```text
distance 越小越相似
```

转换成 similarity：

```python
vector_similarity = max(0.0, 1.0 - distance)
```

### BM25 normalization

BM25 分数范围不固定，对每组 query 做 min-max normalization：

```python
bm25_normalized = (
    score - min_score
) / (
    max_score - min_score
)
```

如果最大值等于最小值，则统一设为 `0.0`。

### 加权公式

初始：

```text
vector_weight=0.7
bm25_weight=0.3
```

公式：

```text
hybrid_score =
0.7 * vector_similarity
+ 0.3 * bm25_normalized
```

只在单路出现的文档：

- 缺失分数按 0 处理；
- 或使用只对存在信号加权的方式。

S09 第一版采用简单方案：

```text
缺失分数按 0
```

便于复现。

## 排序规则

融合结果按：

```text
hybrid_score 降序
```

分数相同按：

```text
vector_rank
bm25_rank
child_id
```

稳定排序。

## 无答案题处理

BM25 没有经过校准的拒答阈值。

第一版 Hybrid 保持：

```text
普通无答案题仍以 vector distance_threshold 为主
```

原因：

- 避免纯 BM25 通用词重叠产生大量误召回；
- 先测试融合对有效问题排序的影响；
- 无答案拒答策略在后续安全阶段单独校准。

这意味着：

```text
S09 Hybrid 主要改变 answerable questions 的候选排序
```

## 评测指标

继续使用：

```text
retrieval_passed
Hit@1
Hit@4
Recall@4
MRR
latency_ms_avg
```

新增：

```text
vector_only_candidates
bm25_only_candidates
overlap_candidates
fused_candidate_count
```

## 对比实验

S09 将比较：

```text
vector
BM25
RRF hybrid
weighted hybrid 0.7/0.3
weighted hybrid 0.5/0.5
```

必须保留每个变体的：

- 配置；
- summary；
- 失败题；
- 融合候选统计。

## 成功条件

Hybrid 至少满足以下之一才算有效：

1. retrieval_passed 高于 vector 的 45；
2. Recall@4 高于 0.9815；
3. Hit@1 或 MRR 明显更高；
4. E33 被修复；
5. 在不降低通过数的前提下，无答案误召回更少。

如果 Hybrid 没有超过 vector：

```text
保留结论，不强推 Hybrid。
```

## 硬边界

1. 不重新分块；
2. 不修改 child；
3. 不修改 eval_set；
4. RRF 与 weighted 分开实验；
5. 每次只改变融合策略；
6. 不能只报告最佳结果，必须报告失败和持平情况；
7. E33 是重点观察题，但不是唯一指标。

## 下一步

S09-2 将实现 RRF：

```python
def fuse_rrf(
    vector_hits: list[dict],
    bm25_hits: list[dict],
    k: int = 60,
) -> list[dict]:
    ...
```
