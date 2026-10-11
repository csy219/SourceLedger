# S07-3 semantic 参数扫描结果

## 扫描范围

```text
candidate_k: 4, 6, 10, 20
threshold: 0.35, 0.40, 0.45, 0.50, 0.55
metric_k: 4
chunk_mode: semantic
collection: semantic_chunk_baseline
```

共 20 组配置，每组运行 46 条问题。

## 统一结果

所有 20 组配置得到完全相同的指标：

```text
retrieval_passed=45
Hit@1=0.9286
Hit@4=1.0
Recall@4=0.9815
MRR=0.9563
failed_ids=["E33"]
```

## 为什么 candidate_k 不影响指标

当前指标只计算前 `metric_k=4` 个候选。

```text
candidate_k=4
candidate_k=6
candidate_k=10
candidate_k=20
```

虽然查询返回的候选数量不同，但：

1. 前 4 名顺序不变；
2. expected_ranks 只接收 `hits[:4]`；
3. Hit@1、Hit@4、Recall@4、MRR 都只看前 4；
4. 因此 candidate_k 变化不会影响这些指标。

它可能影响：

- 后续 rerank 的候选池；
- parent-aware 去重和来源多样性；
- 回答上下文的选择范围。

但不影响当前纯向量 Top-4 排名。

## 为什么 threshold 不影响指标

在 0.35 到 0.55 范围内：

1. 有标准来源的题，标准来源排名和距离均未变化；
2. 三条普通无答案题在 0.35 到 0.55 内都没有错误命中；
3. 因此 `source_check=none` 的判定没有变化；
4. retrieval_passed 保持 45。

这说明 threshold 在当前语料上不是瓶颈，但生产环境仍需要根据真实 bad case 重新校准。

## 失败题

唯一失败题始终是：

```text
E33
```

标准来源：

```text
Agent平台需求说明.pdf 第 2 页
AI应用开发知识手册.pdf 第 9 页
```

semantic 排名：

```text
Agent平台需求说明.pdf 第 2 页：第 1
AI应用开发知识手册.pdf 第 9 页：第 5
```

由于 `source_check=all`，第二名没有进入前 4，因此整题失败。

## 结论

1. 调整 candidate_k 无法解决 E33；
2. 调整 threshold 无法解决 E33；
3. 当前瓶颈是排序，不是召回数量或阈值；
4. 下一步应进入 BM25 和混合检索；
5. canonical 参数继续保持：

```text
candidate_k=10
metric_k=4
threshold=0.5
```

## 为什么保留 candidate_k=10

虽然 4、6、10、20 的 Top-4 指标相同，但：

- 4 没有给 rerank 留候选空间；
- 6 候选空间仍偏小；
- 10 足够覆盖 53 个 child 中的主要候选；
- 20 会增加后续 rerank 成本；
- 10 是当前精度、扩展空间和成本的平衡点。

## S07-3 完成结论

纯向量检索参数已经完成扫描。

结论：

```text
向量 Top-4 已达到稳定上限
参数扫描无法修复 E33
必须引入关键词信号、混合检索或 rerank
```
