# S11-4 Metadata Filter Hybrid 结果

## 配置

```text
retrieval=metadata_filter_rrf
candidate_k=10
metric_k=4
distance_threshold=0.5
rrf_k=60
```

## 结果

| 指标 | 结果 |
| --- | ---: |
| cases | 46 |
| retrieval_passed | 45 |
| retrieval_accuracy | 0.9783 |
| Hit@1 | 0.9762 |
| Hit@4 | 1.0 |
| Recall@4 | 0.9815 |
| MRR | 0.9881 |
| 平均延迟 | 22.35 ms |
| p50 延迟 | 18.70 ms |
| 最大延迟 | 185.21 ms |

失败题：

```text
E33
```

## 过滤统计

```text
filter_applied_count=16
filter_fallback_count=0
```

过滤原因：

```text
explicit_source=11
none=28
multi_source=2
travel_without_version=3
comparison=2
```

## 与 S09 RRF 对比

| 指标 | S09 RRF | S11 Filtered | 变化 |
| --- | ---: | ---: | ---: |
| retrieval_passed | 45 | 45 | 0 |
| Hit@1 | 0.9762 | 0.9762 | 0 |
| Hit@4 | 1.0 | 1.0 | 0 |
| Recall@4 | 0.9815 | 0.9815 | 0 |
| MRR | 0.9881 | 0.9881 | 0 |
| 平均延迟 | 23.99 ms | 22.35 ms | -1.64 ms |

## E37 修正

最初的硬日期过滤会把“2026 年 11 月应该适用哪一版差旅制度？”过滤为只查 v2，导致 v1 丢失并出现回归。

修正后：

```text
只有明确 v1/v2/版本1/版本2 才做单版本过滤
仅有日期时保留两个版本
```

因此 E37 恢复通过。

## 结论

Metadata Filter：

1. 没有提高检索通过数；
2. 没有提高 Hit@1、Recall@4 或 MRR；
3. 没有造成回归；
4. 延迟略低；
5. E33 仍失败。

当前 metadata filter 的主要价值是：

- 明确来源时减少无关候选；
- 避免错误版本混入；
- 对比题保持两个版本；
- 为以后更大语料和更多版本做准备。

但在这套 46 题中，它不是当前指标的主要瓶颈。

## 下一步

S11-5 将完成：

- S09 RRF 与 S11 Filtered Hybrid 的逐题比较；
- 检查是否有改进、回归和共同失败；
- 检查过滤应用题的排名变化；
- 判断是否默认开启 metadata filter。
