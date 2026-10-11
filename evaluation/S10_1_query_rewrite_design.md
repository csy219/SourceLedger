# S10-1 Query Rewrite 与 Multi-query 策略

## 目标

在原始查询之外生成两种辅助查询：

```text
original
semantic rewrite
keyword query
```

分别执行 vector + BM25 检索，再用 RRF 做多查询融合。

重点观察：

```text
E33 是否改善
Recall@4 是否提高
Hit@1 是否提高
MRR 是否提高
无答案题是否回归
```

## 为什么需要 Query Rewrite

E33：

```text
RepoPilot 的审计日志字段与知识手册中的 trace 字段有哪些共同关注点？
```

问题同时包含：

- 平台需求：审计日志字段；
- 知识手册：trace；
- 跨文档比较关系。

原始查询的向量可能偏向“审计日志字段”，导致知识手册第 9 页排第 5。

辅助查询可以更明确地强调：

```text
可观测性 trace 输入输出 token 工具调用 错误
```

以及关键词：

```text
trace user_id task_id tool_name
```

## 查询类型

每题最多生成 3 条查询：

### 1. Original

```text
原始问题
```

不修改，保留原始召回能力。

### 2. Semantic Rewrite

目标：

- 展开语义；
- 消除口语化表达；
- 保留核心实体；
- 不添加资料外事实。

示例：

```text
RepoPilot 的审计日志字段和知识手册中的 trace 字段分别记录什么，它们共同关注哪些可观测性信息？
```

### 3. Keyword Query

只保留：

- 中文关键词；
- 英文标识符；
- 变量名；
- 数字；
- 版本号。

示例：

```text
审计日志 trace user_id task_id tool_name 输入 输出 耗时 token 错误
```

## LLM 输出格式

必须返回合法 JSON：

```json
{
  "semantic": "语义改写后的一个问题",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "keyword_query": "关键词组合后的查询"
}
```

约束：

1. 不回答问题；
2. 不输出分析过程；
3. 不引入文档外事实；
4. 保留原始变量名和数字；
5. 最多 12 个关键词；
6. 改写必须仍然表达原问题意图。

## Prompt 草案

```text
你是检索查询改写器。

任务：
1. 将用户问题改写成一个更适合语义检索的问题；
2. 提取 5-12 个检索关键词；
3. 生成一个关键词查询；
4. 保留 user_id、task_id、tool_name、trace、p95、百分比和版本日期；
5. 不要回答问题，不要增加资料外事实。

只返回 JSON：
{
  "semantic": "...",
  "keywords": ["...", "..."],
  "keyword_query": "..."
}

用户问题：
{question}
```

## 多查询检索流程

对每条生成查询：

```text
query
→ vector top10
→ BM25 top10
```

最终使用全局 RRF：

```text
对每条 query：
    vector rank 提供 1/(k+rank)
    BM25 rank 提供 1/(k+rank)

同一个 child 被多条查询命中时，RRF 分数累加
```

初始：

```text
rrf_k=60
每查询权重=1.0
```

## 查询去重

改写后如果与原始查询或另一条查询完全相同：

```text
只保留一次
```

避免重复累加同一 query 的分数。

## 失败回退

如果 LLM：

1. 返回非法 JSON；
2. 超时；
3. 返回空结果；

则只使用：

```text
original query
```

不能因为 Query Rewrite 失败导致原本正确的检索回归。

## 缓存

46 条问题固定，因此第一次生成后写入：

```text
evaluation/query_rewrite/S10_2_rewrites.json
```

后续实验直接读取缓存。

这样：

- 避免重复 API 调用；
- 保证实验可复现；
- 分离“改写质量”和“随机模型波动”。

## 无答案题处理

保持与 S09 相同：

```text
普通无答案判定仍以原始 query 的 vector threshold 为主
```

原因：

- 多查询可能引入更多通用词；
- 不能因为辅助查询产生的新候选导致无答案题误答；
- 拒答策略单独验证。

## 评测指标

保留：

```text
retrieval_passed
Hit@1
Hit@4
Recall@4
MRR
latency_ms
```

新增：

```text
rewrite_latency_ms
query_count_avg
duplicate_query_count
rewrite_fallback_count
```

对比：

```text
S09 RRF single-query
vs
S10 Multi-query RRF
```

## 成功条件

至少满足一个：

1. retrieval_passed 高于 45；
2. Recall@4 高于 0.9815；
3. Hit@1 或 MRR 高于 S09 RRF；
4. E33 被修复；
5. 无答案题没有新增误召回。

如果没有提升：

```text
保留原始查询，不强行启用改写。
```

## 硬边界

1. 不修改 semantic child；
2. 不修改 eval_set；
3. 每查询仍取 top10；
4. metric_k 仍为 4；
5. 原始查询必须始终保留；
6. Query Rewrite 失败必须回退；
7. 需要报告 API 成本和额外延迟；
8. 不能只汇报 E33，必须比较完整 46 题。

## 下一步

S10-2 将实现：

```python
def rewrite_query(
    question: str,
) -> dict[str, Any]:
    ...
```

并输出：

```python
{
    "original": "...",
    "semantic": "...",
    "keyword_query": "...",
    "keywords": [...],
}
```
