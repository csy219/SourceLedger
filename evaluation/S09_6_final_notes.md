# S09-6 Hybrid Retrieval 阶段总结

## 阶段目标

在相同 53 个 semantic child 和 46 条评测集上，比较：

```text
vector
BM25
RRF
weighted 0.7/0.3
weighted 0.5/0.5
```

判断两路检索是否能互补。

## 指标对比

| 变体 | retrieval_passed | Hit@1 | Hit@4 | Recall@4 | MRR | 平均延迟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vector | 45 | 0.9286 | 1.0 | 0.9815 | 0.9563 | 23.40 ms |
| BM25 | 43 | 0.7381 | 1.0 | 0.9444 | 0.8611 | 0.59 ms |
| RRF | 45 | 0.9762 | 1.0 | 0.9815 | 0.9881 | 23.99 ms |
| weighted 0.7/0.3 | 45 | 0.9286 | 1.0 | 0.9815 | 0.9643 | 23.99 ms |
| weighted 0.5/0.5 | 44 | 0.9048 | 1.0 | 0.963 | 0.9524 | 23.99 ms |

## 最佳变体

选择：

```text
rrf
```

原因：

1. retrieval_passed 保持 45；
2. Hit@1 从 0.9286 提升到 0.9762；
3. MRR 从 0.9563 提升到 0.9881；
4. Recall@4 保持不变；
5. 没有出现相对 vector 的逐题回归；
6. 延迟增加很小。

## 回归分析

### BM25

相对 vector：

```text
improved: 无
regressed: E30, E31
both_failed: E33
```

BM25 单独使用会丢失部分跨页/多来源证据。

### weighted 0.7/0.3

```text
improved: 无
regressed: 无
both_failed: E33
```

无回归，但排序提升小于 RRF。

### weighted 0.5/0.5

```text
improved: 无
regressed: E30
both_failed: E33
```

BM25 权重过高导致 E30 回归。

## 互补性结论

RRF：

- 提高了首个正确来源的排名；
- 没有新增整题通过；
- 没有修复 E33；
- 没有造成逐题回归。

当前结果说明：

```text
Hybrid 改善排序质量
Hybrid 尚未改善整题覆盖
```

## E33 仍然失败

各变体排名：

```text
vector:       [1, None]
BM25:         [2, None]
RRF:          [1, None]
weighted 0.7: [2, None]
weighted 0.5: [2, None]
```

知识手册第 9 页：

```text
vector 第 5
RRF 第 5
weighted 0.7 第 6
weighted 0.5 第 5
```

没有变体把第二个标准来源推入前 4。

## 为什么 RRF 没有修复 E33

RRF 只能重新排列已经出现在候选池中的 child。

如果关键 child：

1. 不在 vector 前 10；
2. 不在 BM25 前 10；
3. 或原始排名过低；

融合无法凭空召回。

E33 需要更上层改进：

- query rewrite；
- 多查询召回；
- parent-aware retrieval；
- rerank；
- 来源多样性约束。

## 阶段结论

1. RRF 是当前最佳 Hybrid 变体；
2. RRF 改善 Hit@1 和 MRR，不增加通过数；
3. BM25 权重过高会引入回归；
4. BM25 没有独有通过题，但有排序贡献；
5. E33 仍无法通过 fusion 解决；
6. 下一步 Query Rewrite 应重点尝试改善 E33。

## 阶段产物

- `S09_1_hybrid_design.md`
- `S09_2_rrf_fusion.py`
- `S09_3_weighted_fusion.py`
- `S09_4_hybrid_eval.py`
- `S09_5_compare_hybrid_variants.py`
- `S09_6_final_notes.md`
- `reports/S09_4_hybrid_variants.json`
- `reports/S09_5_hybrid_comparison.json`

## 下一步

S10 Query Rewrite：

- 对原始问题生成改写；
- 提取精确关键词；
- 生成多个子查询；
- 用 RRF Hybrid 做多查询召回；
- 检查是否能提升 Recall@4 和修复 E33。
