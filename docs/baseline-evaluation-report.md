# SourceLedger A02 基线评测报告

> 任务：A02 复现现有评测结果  
> 执行日期：2026-10-08  
> 结论：核心评测全部复现成功，发现的 2 个可复现性问题均已修复并验证

---

## 1. 基线目录

所有本次评测报告统一位于：

```text
C:\Users\ASUS\Desktop\agent-learningstage1\project_a\evaluation\reports\baseline-2026-10-08
```

包含：

```text
chunk_fixed.json
chunk_structure.json
chunk_semantic.json
chunk_parent_child.json
vector.json
bm25.json
hybrid.json
rerank_hybrid.json
rerank_comparison.json
core_comparison.json
core_comparison.md
suite_manifest.json
S13_5_citation_cost_eval.json
S17_6_fault_injection.json
S18_6_security_regression.json
S19_6_load_test.json
```

---

## 2. 检索对比结果

配置：

```text
cases = 46
metric_k = 4
candidate_k = 20
```

| 指标 | Vector | BM25 | Hybrid |
| --- | ---: | ---: | ---: |
| Retrieval Accuracy | 0.9783 | 0.8696 | 0.9783 |
| Hit@1 | 0.9286 | 0.7381 | 0.9762 |
| Recall@4 | 0.9881 | 0.9643 | 0.9881 |
| MRR | 0.9563 | 0.8611 | 0.9881 |
| nDCG@4 | 0.9569 | 0.8739 | 0.9763 |
| Context Tokens Avg | 787.0217 | 975.9783 | 911.0435 |
| 平均延迟 ms | 24.962 | 0.6665 | 30.6246 |
| 失败用例 | E33 | E30/E31/E33/E39/E40/E41 | E33 |

结论：

- Hybrid 的 Hit@1、MRR 和 nDCG 均优于 Vector 和 BM25。
- Vector 的 Recall@4 与 Hybrid 相同。
- BM25 速度最快，但准确率和召回最低。
- 三种检索共同失败用例为 `E33`。
- Hybrid 没有新增回归，也没有修复 `E33`。

---

## 3. 分块消融结果

| 分块 | Retrieval Accuracy | Hit@1 | MRR | 平均延迟 ms |
| --- | ---: | ---: | ---: | ---: |
| fixed | 0.9783 | 0.9048 | 0.9306 | 24.43 |
| structure | 0.9565 | 0.9762 | 0.9841 | 19.01 |
| semantic | 0.9783 | 0.9286 | 0.9563 | 20.73 |
| parent_child | 0.9783 | 0.9286 | 0.9563 | 19.52 |

parent-child 额外结果：

```text
parent_occurrences_avg = 4
unique_parents_avg = 3.04
context_chars_avg = 729.5
context_tokens_est_avg = 364.22
```

结论：

- structure 的 Hit@1 和 MRR 最高。
- fixed、semantic、parent-child 的 retrieval accuracy 相同。
- parent-child 能扩展回父级上下文，但会增加上下文体积。

---

## 4. Rerank 结果

配置：

```text
backend = noop
model = BAAI/bge-reranker-v2-m3
```

| 指标 | No Rerank | Rerank | Delta |
| --- | ---: | ---: | ---: |
| Retrieval Passed | 45 | 45 | 0 |
| Hit@1 | 0.9762 | 0.9762 | 0 |
| Recall@4 | 0.9815 | 0.9815 | 0 |
| MRR | 0.9881 | 0.9881 | 0 |
| nDCG@4 | 0.8914 | 0.8914 | 0 |
| 平均延迟 ms | 28.64 | 28.67 | +0.03 |

结论：

- 当前 Rerank 是 noop 实验，所以没有质量变化。
- 需在后续 B05 中接入真实条件 Rerank，并重新做质量与延迟对比。
- `E31`、`E33`、`E34` 被保留为聚焦回归用例。

---

## 5. Context / Citation 结果

```text
cases = 46
failed_cases = 0
invalid_citation_count = 0
citation_precision_avg = 0.2807
citation_recall_avg = 1.0
context_tokens_avg = 451.087
context_tokens_max = 851
context_tokens_min = 47
source_diversity_avg = 0.2383
conflict_cases = 3
conflict_covered_cases = 3
injection_cases = 2
injection_contained_cases = 2
budget_violation_cases = 0
```

结论：

- 与历史基线完全一致。
- Citation recall 为 1.0。
- 冲突覆盖 3/3。
- Injection 覆盖 2/2。
- 没有预算违规。
- 页面级 citation precision 较低是现有最小证据标注导致的诊断现象，不是硬失败。

---

## 6. 安全回归结果

```text
scenarios = 5
passed = 5
failed = 0
all_passed = true
```

覆盖：

```text
security_fixtures
prompt_injection
no_evidence
context_integrity
tool_failure
```

关键结果：

- 12 类安全 fixture 加载成功。
- 直接和间接 Prompt Injection 被检测。
- 无证据问题会拒答。
- v1/v2 冲突同时保留。
- 伪造 citation `C99` 被识别为非法。
- 危险命令被阻断。
- 超时、非零退出和权限拒绝被结构化处理。

---

## 7. 故障注入结果

```text
scenarios = 4
passed = 4
failed = 0
all_passed = true
```

覆盖：

```text
timeout_retry_backoff
fallback_circuit_breaker
rate_limit_distributed_lock
request_tool_idempotency
```

关键结果：

- timeout、retry 和 backoff 正常。
- fallback 成功切换到 `bm25_only`。
- circuit breaker 可进入 open 并恢复为 closed。
- 本地和 Redis rate limit 都按阈值拒绝第 3 次请求。
- 分布式锁能阻止并发生效，并在释放后允许重新获取。
- 请求级和工具级幂等均只执行一次。

---

## 8. API 并发压测结果

```text
requests = 20
concurrency = 5
successful = 20
failed = 0
latency_ms_avg = 161.68
latency_ms_p50 = 120.01
latency_ms_p95 = 281.78
latency_ms_max = 343.76
context_tokens_total = 2400
context_tokens_avg = 120
all_passed = true
```

限制：

```text
fake_ask = true
```

该压测只覆盖 API、PostgreSQL、Redis、限流、幂等和 checkpoint，不代表真实大模型吞吐。

---

## 9. 运行命令

### 9.1 完整检索套件

```powershell
cd C:\Users\ASUS\Desktop\agent-learningstage1\project_a
..\.venv\Scripts\python.exe .\evaluation\harness\run_full_suite.py --report-dir .\evaluation\reports\baseline-2026-10-08
```

### 9.2 Context / Citation 评测

导入方式已统一，使用标准模块命令运行：

```powershell
..\.venv\Scripts\python.exe -m evaluation.S13_5_citation_cost_eval --output .\evaluation\reports\baseline-2026-10-08\S13_5_citation_cost_eval.json
```

### 9.3 安全回归

```powershell
..\.venv\Scripts\python.exe -B -m runtime.security.S18_6_security_regression
```

### 9.4 故障注入

```powershell
..\.venv\Scripts\python.exe -B -m runtime.resilience.S17_6_fault_injection_smoke
```

### 9.5 API 并发压测

```powershell
..\.venv\Scripts\python.exe -B -m runtime.api.S19_6_load_test --requests 20 --concurrency 5
```

---

## 10. 问题修复记录

### P1：S13 模块导入方式不一致（已修复）

`S13_5_citation_cost_eval.py` 和 `S13_4_hybrid_citation.py` 使用：

```python
from S13_2_context_packer import pack_context
```

`S13_3_context_trimmer.py` 使用：

```python
from evaluation.S13_2_context_packer import pack_context
```

因此：

- 直接运行文件会找不到 `evaluation`。
- 使用 `-m` 运行会找不到 `S13_2_context_packer`。

修复内容：

- `S13_4_hybrid_citation.py` 改为使用 `evaluation.S13_2_context_packer`。
- `S13_5_citation_cost_eval.py` 改为使用完整 `evaluation.*` 包导入。
- 已验证标准模块入口可以完整运行并生成相同结果。

统一运行方式：

```powershell
..\.venv\Scripts\python.exe -m evaluation.S13_5_citation_cost_eval
```

### P2：core_comparison 默认写到 harness/reports（已修复）

`run_full_suite.py --report-dir` 生成的大部分报告进入指定目录，但 core comparison 默认仍写入：

```text
evaluation\harness\reports
```

修复内容：

- `run_full_suite.py` 现在显式向 `compare_reports.py` 传递 `--output`。
- 输出固定写入本次 `--report-dir`。
- 已验证可生成：

```text
baseline-2026-10-08\core_comparison.json
baseline-2026-10-08\core_comparison.md
```

### P3：Rerank 仍是 noop

当前对比不适合作为真实 Rerank 效果证据，只说明现有接口和回归流程可运行。

### 修复验证

对以下文件执行 `py_compile` 通过：

```text
evaluation\S13_4_hybrid_citation.py
evaluation\S13_5_citation_cost_eval.py
evaluation\harness\run_full_suite.py
evaluation\harness\compare_reports.py
```

---

## 11. A02 结论

除 S13 运行入口外，现有检索、Context、安全、故障和并发评测均已复现。

核心指标与历史记录一致：

```text
Vector Hit@1 = 0.9286
BM25 Hit@1 = 0.7381
Hybrid Hit@1 = 0.9762
Hybrid MRR = 0.9881
Context invalid citation = 0
Security = 5/5
Fault injection = 4/4
Load test failed = 0
```

当前基线可以作为后续高级 RAG 接入前的对照标准。
