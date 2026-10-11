# S12-6 Reranker 阶段总结

## 阶段目标

在 S11 Metadata Filter Hybrid 后增加 cross-encoder rerank。

候选流程：

```text
metadata filter
vector top20
BM25 top20
RRF top20
CrossEncoder rerank
top4
```

## Reranker 状态

```text
backend=cross_encoder
model=BAAI/bge-reranker-v2-m3
device=cpu
load_ms≈3424.65
rerank_latency_ms_avg≈3886.43
```

模型成功加载，真实执行 rerank，没有走 NoOp。

## 对照结果

| 指标 | no rerank k20 | rerank k20 |
| --- | ---: | ---: |
| retrieval_passed | 45 | 44 |
| Hit@1 | 0.9762 | 0.9762 |
| Hit@4 | 1.0 | 1.0 |
| Recall@4 | 0.9815 | 0.963 |
| MRR | 0.9881 | 0.9881 |
| nDCG@4 | 0.8914 | 0.8882 |
| 平均延迟 | 17.86 ms | 3904.29 ms |

## 逐题变化

改进：

```text
E33
```

回归：

```text
E31
E34
```

共同失败：

```text
无
```

Top-1 变化：

```text
E30
E34
E37
E39
```

## E33

RRF：

```text
[1, None]
```

Rerank：

```text
[1, 2]
```

关键变化：

```text
AI应用开发知识手册.pdf 第 9 页
RRF 第 5
→ Rerank 第 2
```

结论：

```text
Rerank 能解决跨文档多来源排序问题
```

## E31

```text
[2, 1]
→ [None, 1]
```

第一个标准来源被降出前 4。

## E34

```text
[1, 3]
→ [None, 1]
```

第二个标准来源被提升，但第一个标准来源被降出前 4。

## 最终决策

当前默认保留：

```text
filtered_hybrid_k20
```

不全局启用 reranker。

原因：

1. 整题通过数下降；
2. Recall@4 下降；
3. nDCG@4 下降；
4. CPU 延迟增加约 218 倍；
5. 虽然修复 E33，但代价是两个回归。

## Reranker 的潜在使用方式

后续可以尝试条件触发：

```text
只在 source_check=all 的多来源题启用
只在标准来源排名位于 4-8 时启用
只 rerank top10
使用 GPU 或更小 reranker
先做来源多样性约束，再 rerank
```

不能直接把当前全局 rerank 放进生产路径。

## 阶段产物

- `S12_1_reranker_design.md`
- `S12_2_reranker_adapter.py`
- `S12_3_rerank_hybrid.py`
- `S12_4_rerank_result_notes.md`
- `S12_5_compare_rerank_results.py`
- `S12_6_final_notes.md`
- `reports/S12_3_rerank_hybrid.json`
- `reports/S12_5_rerank_comparison.json`

## 下一步

S13 Context packing、上下文管理与 citation：

- 去重；
- 来源多样性；
- token 预算；
- 冲突提示；
- 历史裁剪与摘要；
- citation precision；
- faithfulness。
