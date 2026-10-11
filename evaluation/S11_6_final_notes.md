# S11-6 Metadata Filter 阶段总结

## 阶段目标

在 S09 RRF Hybrid 基础上增加 metadata filter：

- 明确来源时限制 `source`；
- 明确版本时限制 v1 或 v2；
- 对比题保留两个版本；
- 多来源问题不过滤；
- 过滤后无候选时回退全库。

## 过滤规则修正

只有明确出现：

```text
v1
v2
版本1
版本2
第一版
第二版
```

才进行单版本过滤。

只有日期：

```text
2026-01-01
2026-10-01
2026 年 11 月
```

保留两个版本。

原因：

```text
E37 需要同时引用 v1 和 v2 才能证明版本冲突
```

最初错误过滤为只查 v2，导致 E37 回归；修正后恢复通过。

## 最终结果

| 指标 | S11 Filtered |
| --- | ---: |
| retrieval_passed | 45 / 46 |
| retrieval_accuracy | 0.9783 |
| Hit@1 | 0.9762 |
| Hit@4 | 1.0 |
| Recall@4 | 0.9815 |
| MRR | 0.9881 |
| 平均延迟 | 22.35 ms |

失败题：

```text
E33
```

## 过滤统计

```text
filter_applied_count=16
filter_fallback_count=0
```

原因分布：

```text
explicit_source=11
none=28
multi_source=2
travel_without_version=3
comparison=2
```

## 与 S09 RRF 对比

所有检索质量指标完全持平：

```text
retrieval_passed=45
Hit@1=0.9762
Hit@4=1.0
Recall@4=0.9815
MRR=0.9881
```

延迟：

```text
23.99 ms -> 22.35 ms
```

逐题：

```text
improved: 无
regressed: 无
both_failed: E33
top1_changed: E40
filtered_rank_changed: 无
```

## 为什么没有提升

1. 46 题中只有 16 条触发过滤；
2. 这些题原本多数已经返回正确来源；
3. 过滤后的前 4 标准来源排名没有变化；
4. E33 是多来源题，不允许单文件过滤；
5. 当前主要瓶颈仍是跨文档排序，不是来源噪声。

## 为什么仍然保留 S11 Filtered

保留原因：

- 指标不下降；
- 无逐题回归；
- 延迟略低；
- 明确来源时减少搜索空间；
- 明确版本时能防止错误版本混入；
- 对比题保持双版本；
- 为未来更大的文档库和更多版本提供安全约束。

最终选择：

```text
s11_filtered
```

它是安全的 metadata 约束层，不是指标提升层。

## 风险

1. 意图解析错误可能过滤正确来源；
2. 多来源识别仍依赖关键词；
3. 日期没有做软权重，只保持双版本；
4. E33 仍未解决；
5. 语料扩大后需要重新校验 source 匹配；
6. 过滤为空虽然会回退，但回退会增加一次检索。

## 阶段产物

- `S11_1_metadata_filter_design.md`
- `S11_2_metadata_intent.py`
- `S11_3_filtered_hybrid.py`
- `S11_4_metadata_filter_result_notes.md`
- `S11_5_compare_filtered_hybrid.py`
- `S11_6_final_notes.md`
- `reports/S11_3_filtered_hybrid.json`
- `reports/S11_5_filtered_comparison.json`

## 下一步

S12 Reranker：

- 扩大候选到 top10/top20；
- 使用 cross-encoder 重新排序；
- 观察 E33 第 5 名能否进入前 4；
- 对比 rerank 前后 Hit@1、MRR、nDCG 和延迟。
