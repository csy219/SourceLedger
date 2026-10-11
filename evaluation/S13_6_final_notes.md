# S13-6 最终总结：Context Packing、历史管理与 Citation

## 1. 阶段目标

S13 解决的是检索结果进入大模型之前的上下文质量问题：

- 去掉重复正文
- 避免单一来源或单一页面占满上下文
- 控制上下文 token
- 保留 v1/v2 冲突
- 标记 instruction injection
- 生成可追踪的 citation
- 裁剪历史并保留完整 tool-call round

## 2. 最终产物

- `S13_2_context_packer.py`
- `S13_3_context_trimmer.py`
- `S13_4_hybrid_citation.py`
- `S13_5_citation_cost_eval.py`
- `reports/S13_4_hybrid_citation.json`
- `reports/S13_5_citation_cost_eval.json`

## 3. 评测结果

评测集：

```text
cases = 46
```

硬性结果：

```text
failed_cases = 0
invalid_citation_count = 0
citation_recall_avg = 1.0
conflict_cases = 3
conflict_covered_cases = 3
injection_cases = 2
injection_contained_cases = 2
budget_violation_cases = 0
```

上下文成本：

```text
context_tokens_avg = 451.087
context_tokens_max = 851
context_tokens_min = 47
budget_used_max = 1057
```

上下文质量：

```text
duplicate_text_count_sum = 0
selected_count_sum = 387
unique_sources_sum = 86
suspicious_count_sum = 10
source_diversity_avg = 0.2383
```

页面级上下文 precision：

```text
context_page_precision_avg = 0.2807
```

## 4. 收益

- S13-2 将候选 chunk 统一转换为受控上下文材料。
- S13-3 将 system、history、retrieval 和当前问题组装成最终 messages。
- tool-call round 被当作不可拆分单元，历史裁剪不会只保留调用或只保留结果。
- v1/v2 冲突在 3 条冲突 case 中全部被覆盖。
- injection 内容被保留为不可信资料，同时在上下文中明确警告。
- 所有生成的 citation 都能在 `context_text` 中找到，`invalid_citation_count=0`。
- 46 条 case 的最终上下文全部低于 3000 token 总预算。
- S13-4 已接入真实 filtered Hybrid 结果，不再只跑手写 demo。

## 5. 回归与限制

- `citation_precision_avg=0.2807` 是页面级上下文精确率，不是最终答案引用精确率。
- 当前评测集的 `expected_sources` 是最小证据标注，不是完整相关页面全集，因此低页面 precision 不能直接判定为系统失败。
- `source_diversity_avg=0.2383` 是诊断指标，不是硬门槛。单文档问题在同一来源命中多个页面时，该值天然较低。
- S13-5 尚未生成模型答案，因此还没有真正的 `answer_citation_precision` 和 `faithfulness` 指标。
- S13-3 的工具调用历史和长对话主要使用构造数据验证，后续接入真实多轮 Agent 后还需要回归测试。
- S12 的 reranker 没有全局启用，S13 当前接入的是 filtered Hybrid 候选，不是 rerank 候选。

## 6. 失败 case 分析

S13-5 本次没有硬性失败：

```text
failed_cases = 0
failed_ids = []
```

需要继续观察的是页面级 precision 较低的 case：

```text
E09
E10
E13
E20
E08
E11
E12
E15
```

这些 case 的 `citation_recall` 都是 `1.0`，但页面 precision 较低。当前最可能的原因是上下文包含同一文档的多个相关页面，而评测集只标注了最小必要证据页。

## 7. 下一阶段

S14 进入 Harness v1：

- 统一运行固定、结构、语义、父子分块
- 统一运行 vector、BM25、Hybrid、rerank 和 context packing
- 输出统一 JSON 报告
- 进行版本对比和失败分类

