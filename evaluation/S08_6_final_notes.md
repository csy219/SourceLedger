# S08-6 BM25 关键词检索阶段总结

## 阶段目标

在完全相同的 53 个 semantic child 和 46 条评测集上，增加纯 BM25 关键词检索，判断它是否能补强向量检索。

## BM25 配置

```text
retrieval=bm25_only
chunk_mode=semantic
candidate_k=10
metric_k=4
score_threshold=0.0
k1=1.5
b=0.75
document_count=53
```

## Tokenizer

中文：

```text
单字 + 双字 bigram
```

代码标识符：

```text
保留完整 token
按 _ . - 拆分
```

数字和日期：

```text
90
429
5%
p95
2026-10-01
```

## BM25 指标

| 指标 | BM25 |
| --- | ---: |
| retrieval_passed | 40 / 46 |
| retrieval_accuracy | 0.8696 |
| Hit@1 | 0.7381 |
| Hit@4 | 1.0 |
| Recall@4 | 0.9444 |
| MRR | 0.8611 |
| 平均延迟 | 0.54 ms |

## Vector 与 BM25 对比

| 指标 | vector | BM25 | BM25-vector |
| --- | ---: | ---: | ---: |
| retrieval_passed | 45 | 40 | -5 |
| retrieval_accuracy | 0.9783 | 0.8696 | -0.1087 |
| Hit@1 | 0.9286 | 0.7381 | -0.1905 |
| Hit@4 | 1.0 | 1.0 | 0 |
| Recall@4 | 0.9815 | 0.9444 | -0.0371 |
| MRR | 0.9563 | 0.8611 | -0.0952 |
| 平均延迟 | 24.39 ms | 0.54 ms | -23.85 ms |

## 覆盖分析

```text
vector_passed=45
bm25_passed=40
union_passed=45
intersection_passed=40
vector_unique=5
bm25_unique=0
both_failed=1
```

vector 独有通过：

```text
E30
E31
E39
E40
E41
```

BM25 独有通过：

```text
无
```

共同失败：

```text
E33
```

## 失败分析

### E30

- vector 通过；
- BM25 只命中第 6 页；
- 第 5 页未进入前 4。

### E31

- vector 通过；
- BM25 只命中第 7 页；
- 第 4 页未进入前 4。

### E33

- vector 排名：`[1, None]`；
- BM25 排名：`[2, None]`；
- 知识手册第 9 页在 vector 中排第 5，在 BM25 中排第 7；
- BM25 没有修复 E33。

### E39-E41

三条普通无答案题被 BM25 误召回：

- 问题和部分文档共享通用词；
- BM25 只看词重叠，无法稳定理解“资料不足应拒答”；
- `score_threshold=0.0` 无法过滤这些正分误命中。

## 收益

1. BM25 实现正确；
2. 中文和代码 tokenizer 可复用；
3. 检索速度极快；
4. Hit@4 达到 1.0；
5. BM25 分数和 metadata 可与 vector 结果对齐；
6. 为 S09 Hybrid 提供候选来源。

## 局限

1. BM25 通过数低于 vector；
2. BM25 没有独有通过题；
3. Hit@1、Recall@4、MRR 均下降；
4. 无答案题误召回；
5. E33 仍失败；
6. BM25 单独使用不能替代向量。

## 阶段结论

```text
BM25 是互补信号，但目前尚未单独增加整题通过数。
```

它适合进入 Hybrid 候选融合，但是否能提升最终指标尚需 S09 实验证明。

不能因为“加了 BM25”就默认效果会变好。

## 下一步

S09 Hybrid Retrieval 将比较：

1. RRF；
2. 加权分数融合；
3. 向量候选 + BM25 候选去重；
4. 来源多样性约束。

目标是判断 BM25 能否改善 vector 的排序，而不是只增加候选数量。
