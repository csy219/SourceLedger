# S11-1 Metadata Filter 与阈值策略

## 目标

利用 child metadata 约束检索范围，并校准阈值：

- 明确文件来源时，只检索对应文件；
- 明确版本时，只检索对应版本；
- 对比题必须同时保留两个版本；
- 无明确 metadata 意图时不过滤；
- 不通过过滤破坏 Recall。

## 当前 metadata

每个 child 包含：

```text
source
page
heading
block_type
block_index
chunk_index
semantic_group_size
block_indices
parent_id
```

可用于过滤：

```text
source
page
block_type
heading
```

当前语料和版本：

```text
AI应用开发知识手册.pdf
Agent平台需求说明.pdf
差旅报销制度_v1.pdf
差旅报销制度_v2.pdf
```

## Metadata 意图识别

### 文件来源

关键词映射：

| 查询词 | source 过滤 |
| --- | --- |
| 知识手册、RAG 手册 | `AI应用开发知识手册.pdf` |
| Agent 平台、RepoPilot、平台需求 | `Agent平台需求说明.pdf` |
| 差旅制度、差旅报销 | v1 和 v2 两版 |

### 版本

```text
v1、版本1 -> 差旅报销制度_v1.pdf
v2、版本2 -> 差旅报销制度_v2.pdf
```

### 日期

```text
2026-01-01 之后、v1 -> v1
2026-10-01 之后 -> v2
2026-11 -> v2
```

日期/版本过滤只适用于差旅制度。

### 对比意图

出现以下词时，不能只选一个版本：

```text
两版
两个版本
有什么区别
差异
变化
是否一致
哪一版
```

对比题必须保留：

```text
差旅报销制度_v1.pdf
差旅报销制度_v2.pdf
```

## 过滤规则

1. 没有 metadata 意图：不过滤；
2. 明确单一文件：过滤 source；
3. 明确单一版本：过滤 source；
4. 对比题：保留两个版本；
5. 明确文件但未提版本：保留该文件全部页；
6. 过滤后没有候选：回退到无过滤检索；
7. 过滤只影响候选集合，不修改 child 内容。

## Chroma where 条件

单文件：

```python
{"source": {"$eq": "AI应用开发知识手册.pdf"}}
```

两个版本：

```python
{
    "$or": [
        {"source": {"$eq": "差旅报销制度_v1.pdf"}},
        {"source": {"$eq": "差旅报销制度_v2.pdf"}},
    ]
}
```

多个 source：

```python
{"source": {"$in": ["source1", "source2"]}}
```

## 阈值策略

### Vector distance

当前 canonical：

```text
distance_threshold=0.5
```

S11 扫描：

```text
0.40
0.45
0.50
0.55
```

重点观察：

- 无答案题误召回；
- 多文档题漏召回；
- Hit@1、Recall@4。

### BM25 score

当前 Hybrid：

```text
bm25_score_threshold=0.0
```

S11 第一版不改 BM25 分数阈值，只验证 metadata 过滤。

### 过滤后为空

如果过滤后 vector 和 BM25 都没有候选：

```text
回退到未过滤检索
```

避免错误过滤导致漏答。

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
filter_applied_count
filter_fallback_count
filtered_candidate_count_avg
filter_removed_count_avg
no_answer_false_positive_count
```

## 对比

```text
S09 RRF
vs
S11 Filtered Hybrid
```

重点题：

```text
E35、E36、E37、E38、E46
```

它们涉及 v1/v2、日期和跨文档一致性。

## 成功条件

至少满足一个：

1. retrieval_passed 高于 45；
2. Recall@4 高于 0.9815；
3. Hit@1 或 MRR 高于 S09 RRF；
4. 无答案误召回减少；
5. 过滤不造成任何关键题回归。

如果没有提升：

```text
保留 metadata 解析代码，但默认关闭过滤。
```

## 硬边界

1. 不修改 child；
2. 不修改 eval_set；
3. 对比题不能单版本过滤；
4. 过滤为空必须回退；
5. 阈值扫描不能和 metadata filter 同时混改；
6. 必须记录被过滤掉的候选；
7. E33 不是 S11 的主要目标；
8. 不能只看冲突题，必须比较完整 46 题。

## 下一步

S11-2 实现：

```python
def parse_metadata_intent(
    question: str,
) -> dict[str, Any]:
    ...
```

输出：

```python
{
    "sources": ["..."],
    "reason": "explicit_source|version|comparison|none",
    "is_comparison": False,
}
```
