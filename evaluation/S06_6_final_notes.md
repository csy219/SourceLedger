# S06-6 Parent-child / small-to-big 阶段总结

## 实验目标

保持 child 检索排名不变，在命中后根据 `parent_id` 展开父页面，为回答阶段提供更完整上下文。

## 数据规模

| 项目 | 数量 |
| --- | ---: |
| PDF 文件 | 4 |
| 页面 Parent | 15 |
| Semantic Child | 53 |
| Chroma child 向量 | 53 |

## 四种模式检索指标

| 指标 | fixed | structure | semantic | parent_child |
| --- | ---: | ---: | ---: | ---: |
| retrieval_passed | 45 | 44 | 45 | 45 |
| retrieval_accuracy | 0.9783 | 0.9565 | 0.9783 | 0.9783 |
| Hit@1 | 0.9048 | 0.9762 | 0.9286 | 0.9286 |
| Hit@4 | 0.9762 | 1.0 | 1.0 | 1.0 |
| Recall@4 | 0.963 | 0.963 | 0.9815 | 0.9815 |
| MRR | 0.9306 | 0.9841 | 0.9563 | 0.9563 |

parent_child 与 semantic 的检索排名完全一致，因为父块展开发生在 child 排名之后。

## 上下文展开指标

| 指标 | 结果 |
| --- | ---: |
| parent_occurrences_avg | 4 |
| unique_parents_avg | 3.04 |
| context_chars_avg | 729.5 |
| context_chars_max | 1140 |
| context_tokens_est_avg | 364.22 |

解释：

- 前 4 个 child 平均全部具有 parent_id；
- 去重后平均对应约 3.04 个父页面；
- 平均准备 729.5 个上下文字符；
- 最大准备 1140 个上下文字符；
- 平均约 364 个预估 token。

## 逐题对比

### parent_child 相对 fixed

- improved：无；
- regressed：无；
- both_failed：E33。

### parent_child 相对 structure

- improved：E32；
- regressed：无；
- both_failed：E33。

### parent_child 相对 semantic

- improved：无；
- regressed：无；
- both_failed：E33。

## E33 分析

E33 标准来源：

- `Agent平台需求说明.pdf` 第 2 页；
- `AI应用开发知识手册.pdf` 第 9 页。

当前失败原因：

1. 知识手册第 9 页没有进入 child 前 4；
2. parent 展开不会改变 child 的排名；
3. 因此不能把排名第 5 或更后的父页面提升进前 4；
4. 同一文档的相似 child 仍可能占据多个候选位置。

## S06 收益

1. Child 能稳定映射到 Parent；
2. 同一 Parent 可以正确去重；
3. 问答上下文由独立 JSON 管理；
4. 已量化回答上下文大小和成本；
5. fixed、structure、semantic 模式没有被破坏。

## S06 局限

1. 当前不会提升 Hit、Recall、MRR；
2. 当前不会改变 retrieval_passed；
3. 尚未做最终 LLM 回答评测；
4. 父页面增加上下文和噪声；
5. 需要额外维护 parent store；
6. 直接注入文本可能随父页面进入上下文，后续必须做安全过滤。

## 关键结论

Current parent-child 是“排名后展开”版本：

```text
child 排名
→ top 4
→ parent 展开
```

它负责上下文完整性，不负责候选重排。

下一步若要改善检索排名，应实现：

```text
先召回前 10 个 child
→ 按 parent_id 去重
→ 每个 parent 保留最佳 child
→ 选择前 4 个不同 parent
```

或者：

```text
over-fetch child
→ parent-aware rerank
→ source diversity constraint
```

## 阶段产物

- `S06_1_design_notes.md`
- `S06_2_parent_child_index.py`
- `parent_store/S06_2_parent_store.json`
- runner 的 `parent_child` 模式
- `S06_4_parent_child_result_notes.md`
- `S06_5_compare_four_chunking_reports.py`
- `reports/parent_child_chunk_baseline.json`
- `reports/S06_5_four_way_comparison.json`

## 下一步

进入 S07，整理并明确当前纯向量检索基线，为 S08 BM25 和 S09 混合检索提供统一比较基准。
