# S10-6 Query Rewrite 与 Multi-query 阶段总结

## 阶段目标

为原始问题生成：

```text
original
semantic
keyword_query
```

分别执行 vector + BM25，再用全局 RRF 融合。

## 改写缓存

```text
LLM 成功：44
fallback：2
缓存记录：46
```

两条 fallback：

```text
怎样用成本和可观测性数据证明缓存与模型路由有效？
两版差旅制度是否都要求提供发票和审批记录？
```

原因是模型两次返回空 content，触发：

```text
ValidationError: Invalid JSON
```

fallback 保留原问题和 tokenizer 关键词查询，不阻断检索实验。

## 多查询配置

```text
query_types=original, semantic, keyword_query
query_weight=1.0 each
rrf_k=60
candidate_k=10
metric_k=4
distance_threshold=0.5
query_count_avg=2.913
```

## 多查询结果

| 指标 | S10 Multi-query |
| --- | ---: |
| retrieval_passed | 45 / 46 |
| retrieval_accuracy | 0.9783 |
| Hit@1 | 0.9524 |
| Hit@4 | 1.0 |
| Recall@4 | 0.9815 |
| MRR | 0.9762 |
| 平均延迟 | 82.59 ms |

失败题：

```text
E33
```

## 与 S09 RRF 对比

| 指标 | S09 RRF | S10 Multi-query | 变化 |
| --- | ---: | ---: | ---: |
| retrieval_passed | 45 | 45 | 0 |
| Hit@1 | 0.9762 | 0.9524 | -0.0238 |
| Hit@4 | 1.0 | 1.0 | 0 |
| Recall@4 | 0.9815 | 0.9815 | 0 |
| MRR | 0.9881 | 0.9762 | -0.0119 |
| 平均延迟 | 23.99 ms | 82.59 ms | +58.60 ms |

## 逐题变化

```text
improved: 无
regressed: 无
both_failed: E33
top1_changed: E34, E38
top1_same_rate: 0.9565
```

## 为什么没有提升

1. semantic 改写和原问题高度相似；
2. keyword query 通过 BM25 引入额外噪声；
3. 三路查询等权，原始高质量 vector 排名被稀释；
4. 同一 child 在多路查询中重复得分；
5. E33 的知识手册第 9 页仍排第 5；
6. 多查询扩大了检索成本，但没有产生新的整题通过。

## 工程结论

当前不启用 S10 Multi-query 作为最终检索路径。

最终检索方案暂时保留：

```text
S09 RRF
```

保留的 S10 资产：

- Query Rewrite 代码；
- 改写缓存；
- fallback 和 retry-fallback；
- 多查询 RRF；
- 完整对比报告。

这些资产可以在其他 Query 权重、阈值或后续 rerank 中复用，但当前不使用。

## 面试价值

可以说明：

```text
Query Rewrite 经真实评测没有超过原 RRF，
Hit@1 和 MRR 下降，
延迟增加约 3.4 倍，
因此没有盲目上线。
```

这是有效的负向工程结论，不是无效工作。

## 阶段产物

- `S10_1_query_rewrite_design.md`
- `S10_2_query_rewrite.py`
- `query_rewrite/S10_2_rewrites.json`
- `S10_3_multiquery_hybrid.py`
- `S10_4_multiquery_result_notes.md`
- `S10_5_compare_multiquery_results.py`
- `S10_6_final_notes.md`
- `reports/S10_3_multiquery_hybrid.json`
- `reports/S10_5_multiquery_comparison.json`

## 下一步

S11 Metadata Filter 与阈值：

- 文件过滤；
- 版本过滤；
- 日期/时间过滤；
- 相似度阈值；
- 改善冲突题和无答案题的判定；
- 避免 Query Rewrite 继续无效扩展。
