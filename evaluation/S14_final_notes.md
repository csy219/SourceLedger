# S14 最终总结：Harness v1 与高级 RAG 消融

## 1. 阶段目标

S14 将 S01-S13 的检索实验统一到同一套 Harness：

- 同一评测集
- 同一 candidate_k 和 metric_k
- 统一 Runner 接口
- 统一指标
- 统一 JSON 报告
- 统一失败分类

## 2. 产物

- `harness/config.py`
- `harness/dataset.py`
- `harness/runners.py`
- `harness/metrics.py`
- `harness/reports.py`
- `harness/run_harness.py`
- `harness/run_suite.py`
- `harness/run_chunk_suite.py`
- `harness/run_rerank_suite.py`
- `harness/compare_reports.py`
- `harness/reports/*.json`

## 3. 检索 Runner 对比

| runner | Retrieval Accuracy | Hit@1 | Recall@4 | MRR | nDCG@4 | Latency Avg | Context Tokens Avg |
|---|---:|---:|---:|---:|---:|---:|---:|
| vector | 0.9783 | 0.9286 | 0.9881 | 0.9563 | 0.9569 | 18.2222 ms | 787.0217 |
| bm25 | 0.8696 | 0.7381 | 0.9643 | 0.8611 | 0.8739 | 0.4270 ms | 975.9783 |
| hybrid | 0.9783 | 0.9762 | 0.9881 | 0.9881 | 0.9763 | 17.7467 ms | 911.0435 |

结论：

- Hybrid 在 Hit@1、MRR 和 nDCG@4 上最好。
- BM25 延迟最低，但排序质量明显弱于 Vector 和 Hybrid。
- Vector 和 Hybrid 的检索通过率相同，但 Hybrid 排序更稳。
- `E33` 在三个 runner 中都失败，是共同的检索难点。
- 当前 Hybrid 没有引入新的回归。

## 4. Chunk Mode 消融

| chunk_mode | Retrieval Accuracy | Hit@1 | Recall@4 | MRR |
|---|---:|---:|---:|---:|
| fixed | 0.9783 | 0.9048 | 0.9630 | 0.9306 |
| structure | 0.9565 | 0.9762 | 0.9630 | 0.9841 |
| semantic | 0.9783 | 0.9286 | 0.9815 | 0.9563 |
| parent_child | 0.9783 | 0.9286 | 0.9815 | 0.9563 |

结论：

- structure 的 Hit@1 和 MRR 较高，但 Retrieval Accuracy 略低。
- semantic 和 parent_child 的 Recall@4 最好。
- parent_child 当前检索排序与 semantic 相同，父块扩展的价值需要继续通过上下文 token 和引用正确率观察。

## 5. Rerank 消融

修复：

- E33：`[1, None] -> [1, 2]`

回归：

- E31：`[2, 1] -> [None, 1]`
- E34：`[1, 3] -> [None, 1]`

结论：

- Rerank 能修复 E33，但会引入 E31 和 E34 回归。
- CPU rerank 延迟远高于原始 Hybrid。
- 因此默认不全局启用 rerank。
- 后续可研究条件触发 rerank，而不是所有 query 都启用。

## 6. 收益

- S01-S13 的实验可以通过 Harness 重跑。
- Vector、BM25、Hybrid 使用统一 Runner 和统一报告结构。
- Chunk mode 形成统一消融入口。
- Rerank 形成独立消融入口。
- Context packing 已接入 RunnerResult。
- 指标包括 Retrieval Accuracy、Hit@1、Recall@4、MRR、nDCG、延迟和上下文 token。
- 能按 case 和 category 定位失败。

## 7. 限制

- 当前 Harness 仍是研究型框架，不是服务化 Runtime。
- parent_child 的父块扩展还需更细的上下文质量和引用评测。
- rerank 只在 CPU 测试，未评估 GPU 和批量优化。
- 当前 context packing 使用 filtered Hybrid 候选，rerank 默认关闭。
- 失败分类仍以检索通过率和 case 差异为主，后续需要加入更细的错误类型。

## 8. 下一阶段

S15 进入 Runtime：

- 执行图
- 状态生命周期
- 失败路径
- 不可恢复点
- 重复执行风险
- Runtime 可复用边界

