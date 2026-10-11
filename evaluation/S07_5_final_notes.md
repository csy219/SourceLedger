# S07-5 纯向量检索 baseline 阶段总结

## 阶段目标

为 S08 BM25、S09 Hybrid Retrieval 和 S12 Rerank 建立唯一、固定的向量检索对照基线。

## Canonical 配置

```text
embedding_model=BAAI/bge-small-zh-v1.5
chunk_mode=semantic
chunk_size=400
overlap=80
semantic_threshold=0.72
candidate_k=10
metric_k=4
distance_threshold=0.5
retrieval=vector_only
rerank=off
bm25=off
```

## Canonical 指标

| 指标 | 结果 |
| --- | ---: |
| retrieval_passed | 45 / 46 |
| retrieval_accuracy | 0.9783 |
| Hit@1 | 0.9286 |
| Hit@4 | 1.0 |
| Recall@4 | 0.9815 |
| MRR | 0.9563 |

失败题：

```text
E33
```

## 参数扫描结论

扫描：

```text
candidate_k: 4, 6, 10, 20
threshold: 0.35, 0.40, 0.45, 0.50, 0.55
metric_k: 4
```

20 组配置的检索质量指标完全相同：

```text
retrieval_passed=45
Hit@1=0.9286
Hit@4=1.0
Recall@4=0.9815
MRR=0.9563
failed_ids=["E33"]
```

原因：

1. `metric_k=4`，指标只评价前 4；
2. candidate_k 增大不会改变前 4 的顺序；
3. 无答案题在 0.35-0.55 内没有错误命中；
4. 调整 threshold 没有改变整题判定。

## 为什么选择 candidate_k=10

虽然 4、6、10、20 的当前指标相同，但：

- 4 没有给 rerank 留候选空间；
- 6 的候选池仍然偏小；
- 10 能覆盖主要 child；
- 20 增加后续 rerank 和上下文成本；
- 10 是当前效果、扩展空间和成本的平衡点。

## 为什么选择 threshold=0.5

- 当前范围 0.35-0.55 对无答案判定稳定；
- 0.5 位于扫描区间中部；
- 与前面所有实验保持一致；
- 后续出现真实 bad case 时再重新标定。

## E33 分析

标准来源：

```text
Agent平台需求说明.pdf 第 2 页
AI应用开发知识手册.pdf 第 9 页
```

当前排名：

```text
Agent平台需求说明.pdf 第 2 页：第 1
AI应用开发知识手册.pdf 第 9 页：第 5
```

由于 `source_check=all`，第二名未进入前 4。

参数扫描不能解决 E33，因为：

- candidate_k 只扩大尾部候选；
- threshold 只过滤低质量候选；
- 两者都不重新排列第 4 和第 5 的顺序。

## 阶段结论

1. semantic 是当前最稳定的纯向量方案；
2. 当前 Top-4 向量排序已经到达参数调节上限；
3. 当前瓶颈是排序质量，不是 top-k 或 threshold；
4. 下一阶段应引入关键词精确匹配；
5. BM25 有望补强 `trace`、`user_id`、`tool_name` 等关键词信号。

## 阶段产物

- `S07_1_baseline_protocol.md`
- `S07_2_semantic_vector_sweep.py`
- `S07_3_semantic_sweep_notes.md`
- `S07_4_select_canonical_baseline.py`
- `S07_5_final_notes.md`
- `reports/S07_2_semantic_vector_sweep.json`
- `reports/S07_4_canonical_vector_baseline.json`

## 下一步

S08 将实现 BM25 关键词检索：

- 中文分词或字符 n-gram；
- 精确关键词、编号和英文变量名匹配；
- 与 canonical vector baseline 对比；
- 检查 BM25 是否能改善 E33。
