# S07-1 纯向量检索 canonical baseline 协议

## 目标

为后续实验提供唯一、固定、可复现的纯向量检索基线：

- S08 BM25；
- S09 Hybrid Retrieval；
- S10 Query Rewrite；
- S12 Rerank。

后续每次改动都必须和本基线使用同一：

- 评测集；
- 文档语料；
- chunk 模式；
- Embedding 模型；
- top-k；
- 距离阈值；
- 指标口径。

## 候选方案

| 模式 | 块数 | retrieval_passed | Hit@1 | Hit@4 | Recall@4 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed | 17 | 45 | 0.9048 | 0.9762 | 0.963 | 0.9306 |
| structure | 77 | 44 | 0.9762 | 1.0 | 0.963 | 0.9841 |
| semantic | 53 | 45 | 0.9286 | 1.0 | 0.9815 | 0.9563 |
| parent_child | 53 child | 45 | 0.9286 | 1.0 | 0.9815 | 0.9563 |

## 选择结论

选择：

```text
semantic
```

作为 canonical vector baseline。

选择原因：

1. retrieval_passed 为 45，与 fixed 持平；
2. Recall@4 为 0.9815，当前最高；
3. Hit@4 为 1.0，每个有标准来源的题至少召回一个正确来源；
4. 修复了 structure 的 E32 回归；
5. 相比 fixed，Hit@1、Hit@4、Recall@4、MRR 均有提升；
6. parent_child 的检索排名与 semantic 完全相同，额外 parent 展开属于回答上下文，不进入 canonical retrieval baseline。

structure 虽然 Hit@1 和 MRR 更高，但：

- retrieval_passed 只有 44；
- 出现 E32 回归；
- 不适合作为稳定基线。

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

## Canonical 结果

```text
cases=46
retrieval_passed=45
retrieval_accuracy=0.9783
Hit@1=0.9286
Hit@4=1.0
Recall@4=0.9815
MRR=0.9563
```

当前唯一失败题：

```text
E33
```

E33 标准来源：

```text
Agent平台需求说明.pdf 第 2 页
AI应用开发知识手册.pdf 第 9 页
```

当前结果：

```text
Agent平台需求说明.pdf 第 2 页：命中
AI应用开发知识手册.pdf 第 9 页：第 5
```

失败原因是 `source_check=all`，第二个来源没有进入前 4。

## 固定实验不变量

后续 S08-S12 不得同时改变多个变量。

每次只修改当前任务对应的一项：

```text
S08：只增加 BM25
S09：只增加向量与 BM25 融合
S10：只增加 Query Rewrite
S12：只增加 Rerank
```

保持固定：

```text
同一 46 条 eval_set
同一 4 份 PDF
同一 semantic children
同一 BGE 模型
同一 metric_k=4
同一评测脚本
```

## S07-2 参数扫描范围

为确认 canonical 参数是否合理，S07-2 将实现：

### candidate_k 扫描

```text
4
6
10
20
```

### distance threshold 扫描

```text
0.35
0.40
0.45
0.50
0.55
```

保持：

```text
metric_k=4
```

原因：

- `candidate_k` 影响召回范围和来源多样性；
- threshold 影响普通无答案题的拒答行为；
- 参数扫描不能改变评测代码；
- 每次扫描必须保存完整报告。

## 需要观察的指标

```text
retrieval_passed
Hit@1
Hit@4
Recall@4
MRR
无答案题误召回数
平均延迟
```

不能只选择 Hit@4 最高的配置，必须同时考虑：

- 无答案题是否正确拒答；
- 多文档题是否通过；
- 延迟是否可接受；
- 配置是否能稳定复现。
