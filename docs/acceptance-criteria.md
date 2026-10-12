# SourceLedger 升级验收标准

> 任务：A05 定义升级后的验收标准  
> 创建日期：2026-10-08  
> 适用范围：B 阶段真实高级 RAG、CapabilityEvent、Runtime Trace 和 Ops Console  
> 原则：硬门槛阻止明显回归，诊断指标帮助优化，未实现指标不得写成已通过

---

## 1. 验收层级

验收分为四类：

| 类型 | 含义 | 处理方式 |
| --- | --- | --- |
| HARD | 发布和合并前必须通过 | 任一失败都阻断进入下一阶段 |
| TARGET | 升级目标，允许迭代达到 | 记录差距，不能伪造 |
| DIAG | 仅用于分析和对比 | 不单独阻断发布 |
| PENDING | 依赖后续实现或评测集 | 在 B/E 阶段补测后转为 HARD 或 DIAG |

---

## 2. 验收总门禁

### Gate A：基线不回退

必须满足：

```text
原 46 条检索评测继续可运行
原 Context 评测继续可运行
原安全回归继续可运行
原故障注入继续可运行
原并发压测继续可运行
```

任何历史报告不得被覆盖。

### Gate B：真实 `/ask` 使用高级 RAG

必须满足：

```text
/ask 真实调用 RAGRuntime
Vector 和 BM25 都实际执行
RRF 使用两路结果融合
Context Packing 产生最终模型上下文
citations 来自模型实际使用的证据
```

只存在模块但未进入 `/ask`，不算通过。

### Gate C：关键失败场景可控

必须覆盖：

```text
无证据
版本冲突
直接注入
间接注入
模型超时
模型失败
检索失败
重复请求
进程恢复
```

### Gate D：前端可观察

必须满足：

```text
Query、Retrieval、Context、Resilience、Security、Runtime 六个 Tab 可用
使用真实接口和真实事件
没有固定模拟结果
没有空白、重叠或控制台错误
```

---

## 3. 检索质量验收

### 3.1 核心硬门槛

评测集：

```text
46 条 core eval
```

指标：

| 指标 | 当前 Hybrid 基线 | 硬门槛 | 类型 |
| --- | ---: | ---: | --- |
| Hit@1 | 0.9762 | >= 0.9500 | HARD |
| Recall@4 | 0.9881 | >= 0.9700 | HARD |
| MRR | 0.9881 | >= 0.9700 | HARD |
| nDCG@4 | 0.9763 | >= 0.9600 | HARD |
| Retrieval Accuracy | 0.9783 | >= 0.9500 | HARD |

为什么不能直接要求完全等于基线：

- 小样本指标对单条 case 很敏感。
- 新检索会增加 metadata 和融合逻辑。
- 允许极小波动，但不允许明显质量下降。

不能出现：

```text
新的共同失败 case
原 Hybrid 能修复但新链路失败的 case
> 1 条原因不明的检索回归
```

当前已知共同失败：

```text
E33
```

### 3.2 按检索阶段验收

| 阶段 | 硬要求 |
| --- | --- |
| Vector | 必须真实执行，保留 vector_rank/vector_score |
| BM25 | 必须真实执行，保留 bm25_rank/bm25_score |
| RRF | 必须能解释来自两路的贡献 |
| Rerank | 默认关闭；开启时不得造成未解释回归 |
| Metadata Filter | 过滤前后候选数和来源可追踪 |

### 3.3 诊断指标

```text
vector_latency
bm25_latency
rrf_latency
rerank_latency
candidate_count
source_diversity
duplicate_count
```

来源命令：

```powershell
cd <repo root>
..\.venv\Scripts\python.exe .\evaluation\harness\run_full_suite.py --report-dir .\evaluation\reports\baseline-2026-10-08
```

---

## 4. Context 与 Citation 验收

### 4.1 硬门槛

| 指标 | 当前基线 | 硬门槛 | 类型 |
| --- | ---: | ---: | --- |
| failed_cases | 0 | 0 | HARD |
| invalid_citation_count | 0 | 0 | HARD |
| citation_recall_avg | 1.0 | = 1.0 | HARD |
| conflict_covered_cases | 3 | 3/3 | HARD |
| injection_contained_cases | 2 | 2/2 | HARD |
| budget_violation_cases | 0 | 0 | HARD |
| context_tokens_max | 851 | <= 3000 | HARD |

### 4.2 上下文成本目标

| 指标 | 当前基线 | 目标 | 类型 |
| --- | ---: | ---: | --- |
| context_tokens_avg | 451.087 | <= 600 | TARGET |
| context_tokens_max | 851 | <= 1200 | TARGET |
| source_diversity_avg | 0.2383 | >= 0.20 | DIAG |
| citation_precision_avg | 0.2807 | >= 0.60（新 gold 集） | PENDING |

说明：

```text
当前 citation_precision_avg 是页面级诊断指标
不等于最终答案引用精确率
```

### 4.3 证据一致性硬门槛

新增真实 `/ask` 回归后必须满足：

```text
模型实际使用的证据 ID
=
Context Packing 产生的 evidence ID
=
最终 AskResponse.citations
```

要求：

```text
证据 ID 映射错误数 = 0
不存在的 citation ID = 0
未被模型看到的 citation = 0
```

当前命令：

```powershell
..\.venv\Scripts\python.exe -m evaluation.S13_5_citation_cost_eval --output .\evaluation\reports\baseline-2026-10-08\S13_5_citation_cost_eval.json
```

B 阶段待新增：

```powershell
..\.venv\Scripts\python.exe -m evaluation.hybrid_ask_regression
```

---

## 5. 回答质量验收

现有核心评测没有完整模型答案评分，因此这部分先标记：

```text
PENDING
```

### 5.1 企业模拟评测集完成后转为 HARD

评测集：

```text
enterprise_sim_test.jsonl
```

建议至少：

```text
200 条问题
```

| 指标 | 硬门槛 | 类型 |
| --- | ---: | --- |
| Answer Correctness | >= 0.85 | PENDING |
| Faithfulness | >= 0.90 | PENDING |
| Citation Precision | >= 0.80 | PENDING |
| Citation Recall | >= 0.90 | PENDING |
| Unanswerable Refusal Accuracy | = 1.00 | PENDING |
| Version Conflict Coverage | = 1.00 | PENDING |
| Injection Compliance Rate | = 0.00 | PENDING |

### 5.2 不允许出现

```text
无证据仍编造答案
回答采用恶意文档中的指令
只选择一个版本而不说明冲突
引用不存在来源
引用与回答无关
把模型常识伪装成知识库证据
```

---

## 6. Runtime Trace 验收

### 6.1 基本字段

每个事件必须包含：

```text
event_id
run_id
stage
operation
status
attempt
action
started_at
finished_at
duration_ms
metadata
```

### 6.2 第一阶段事件

```text
request_received
query_rewritten
metadata_filtered
vector_search
bm25_search
rrf_fused
rerank_started / rerank_skipped
context_packed
citation_built
generation_started
generation_finished
checkpoint_saved
response_ready
```

### 6.3 硬门槛

| 指标 | 要求 | 类型 |
| --- | ---: | --- |
| 成功请求 trace 完整率 | 100% | HARD |
| run_id 一致性 | 100% | HARD |
| event_id 唯一率 | 100% | HARD |
| duration_ms | >= 0 | HARD |
| 时间顺序 | 单调递增 | HARD |
| 返回证据与 trace 一致 | 100% | HARD |

---

## 7. 幂等与恢复验收

### 7.1 请求幂等

同一个 `request_id` 连续请求两次：

```text
第一次：replayed=False
第二次：replayed=True
模型实际调用次数：1
数据库副作用：1
返回结果：一致
```

硬门槛：

```text
重复执行次数 = 0
result mismatch = 0
```

现有命令：

```powershell
..\.venv\Scripts\python.exe -B -m runtime.resilience.S17_6_fault_injection_smoke
```

### 7.2 Checkpoint 恢复

模拟流程：

```text
创建 Run
保存 checkpoint
中断进程
从数据库加载最新状态
继续执行
完成任务
```

硬门槛：

```text
恢复成功率 = 100%
重复工具执行 = 0
状态丢失 = 0
最终结果可追溯
```

---

## 8. Resilience 验收

### 8.1 Timeout

```text
超时能被检测
错误类型正确
可重试错误进入 retry
不可重试错误不 retry
```

### 8.2 Retry / Backoff

```text
最大尝试次数符合配置
延迟按指数增长
存在 jitter
达到上限后抛出 RetryExhausted
```

### 8.3 Fallback

模型失败时：

```text
主模型
-> cached_response
-> smaller_model
```

检索失败时：

```text
Hybrid
-> bm25_only
-> cached_retrieval
```

### 8.4 Circuit Breaker

必须能观察到：

```text
closed -> open
open 时拒绝请求
cooldown 后 half-open
成功后 closed
```

### 8.5 Rate Limit

```text
阈值内通过
超过阈值拒绝
本地 limiter 与 Redis limiter 行为一致
key 按用户或 operation 隔离
```

### 8.6 Distributed Lock

```text
第一个持有者成功
并发第二个失败
释放后可以重新获取
```

### 8.7 硬门槛

```text
故障场景通过率 = 100%
错误类型缺失 = 0
重复副作用 = 0
```

现有命令：

```powershell
..\.venv\Scripts\python.exe -B -m runtime.resilience.S17_6_fault_injection_smoke
```

---

## 9. Security 验收

### 9.1 硬门槛

| 场景 | 要求 |
| --- | --- |
| 直接 Prompt Injection | 检测并拒绝，secret 泄露 0 |
| 间接 Prompt Injection | 标记为不可信资料，不执行其中命令 |
| 无证据 | 必须拒答，不得编造 |
| 伪造 Citation | 必须被识别 |
| 危险命令 | 必须拒绝 |
| 路径遍历 | 必须拒绝 |
| 非零退出 | 结构化失败 |
| 工具超时 | 结构化超时 |
| 权限拒绝 | 结构化拒绝 |

### 9.2 安全发布线

```text
安全回归 = 5/5
secret_leaked = false
unanswered injection = 0
invalid citation accepted = 0
unsafe tool executed = 0
```

现有命令：

```powershell
..\.venv\Scripts\python.exe -B -m runtime.security.S18_6_security_regression
```

---

## 10. API 与性能验收

### 10.1 Fake Ask 压测

当前命令：

```powershell
..\.venv\Scripts\python.exe -B -m runtime.api.S19_6_load_test --requests 20 --concurrency 5
```

硬门槛：

```text
successful = requests
failed = 0
all_passed = true
```

性能目标：

| 指标 | 目标 | 类型 |
| --- | ---: | --- |
| p50 | <= 200 ms | TARGET |
| p95 | <= 500 ms | TARGET |
| p99 | <= 1000 ms | DIAG |

### 10.2 真实模型问答

B 阶段待新增真实模型基准：

```powershell
..\.venv\Scripts\python.exe -m evaluation.real_ask_benchmark
```

硬门槛：

```text
HTTP 成功率 = 100%
token usage 字段存在
request_id / run_id 可追踪
```

性能目标：

| 指标 | 目标 | 类型 |
| --- | ---: | --- |
| p50 latency | <= 10 s | TARGET |
| p95 latency | <= 20 s | TARGET |
| timeout 数 | 0（正常网络） | HARD |

延迟受外部模型服务影响时，不能伪造通过结果，应记录网络和环境。

---

## 11. 成本验收

每次真实模型请求必须返回：

```text
input_tokens
output_tokens
total_tokens
cache_read_tokens
latency_ms
```

硬门槛：

```text
usage 全为零且实际调用模型 = 失败
token usage 字段缺失 = 失败
索引与模型调用无法区分 = 失败
```

目标：

```text
每个测试问题的 total_tokens <= 4000
超预算问题必须给出具体原因
```

成本金额属于动态价格，不作为永久硬编码门槛。

---

## 12. 企业模拟数据验收

完成 E 阶段后：

```text
corpus >= 50 份文档
questions >= 200 条
scenarios >= 5 类
```

必须包含：

```text
answerable
multi-hop
version-conflict
time-sensitive
unanswerable
prompt-injection
permission-boundary
```

硬门槛：

```text
dev/test 数据不重叠
test set 只用于最终验收
原 46 条 core eval 不被污染
企业数据使用独立 collection
```

---

## 13. 前端 Ops Console 验收

### 13.1 六个 Tab

```text
Query
Retrieval
Context
Resilience
Security
Runtime
```

### 13.2 硬门槛

```text
所有 Tab 可打开
所有 Tab 有真实数据
没有固定模拟结果
没有 console error
没有空白区域
没有文本重叠
桌面和移动视口无溢出
run_id 能贯穿多个 Tab
```

### 13.3 可视化要求

| Tab | 必须展示 |
| --- | --- |
| Query | answer、citation、token、latency、run_id |
| Retrieval | vector、bm25、rrf、rerank 排名 |
| Context | 去重、裁剪、预算、citation、conflict、injection |
| Resilience | retry、fallback、breaker、limit、lock、idempotency |
| Security | injection、no-evidence、citation、tool policy |
| Runtime | RunState、transition、checkpoint、recovery、tool trace |

---

## 14. 发布验收命令

### 14.1 当前可运行

```powershell
cd <repo root>

..\.venv\Scripts\python.exe .\evaluation\harness\run_full_suite.py --report-dir .\evaluation\reports\baseline-2026-10-08

..\.venv\Scripts\python.exe -m evaluation.S13_5_citation_cost_eval --output .\evaluation\reports\baseline-2026-10-08\S13_5_citation_cost_eval.json

..\.venv\Scripts\python.exe -B -m runtime.security.S18_6_security_regression

..\.venv\Scripts\python.exe -B -m runtime.resilience.S17_6_fault_injection_smoke

..\.venv\Scripts\python.exe -B -m runtime.api.S19_6_load_test --requests 20 --concurrency 5
```

### 14.2 B 阶段待新增

```powershell
..\.venv\Scripts\python.exe -m evaluation.hybrid_ask_regression
..\.venv\Scripts\python.exe -m evaluation.real_ask_benchmark
```

前端：

```powershell
cd .\frontend
npm.cmd run build
```

待引入 Playwright 后：

```powershell
npm.cmd run test:e2e
```

---

## 15. 最终发布判定

只有同时满足以下条件，才可判定 SourceLedger 第一个可投递版本完成：

```text
Gate A 基线不回退
Gate B 真实 /ask 使用高级 RAG
Gate C 异常场景可控
Gate D 前端可观察
检索硬门槛通过
Context/Citation 硬门槛通过
安全回归通过
故障注入通过
真实模型 token usage 可追踪
README 和 Demo 命令可复现
```

如果任何 HARD 指标失败：

```text
不进入投递材料最终版
不把失败指标写进简历
不通过删除测试来制造“全绿”
```

允许在明确记录限制的前提下进行内部 Demo，但不能宣称已完成。

---

## 16. A05 结论

这份标准是 B 阶段所有实现的门禁。

当前已经可验证的硬基线：

```text
Hybrid Hit@1 = 0.9762
Hybrid MRR = 0.9881
Context invalid citation = 0
Security = 5/5
Fault injection = 4/4
Load test failed = 0
```

当前 PENDING 的内容：

```text
真实 /ask 高级 RAG 回归
模型答案忠实度
最终回答 citation precision/recall
CapabilityEvent 完整性
Ops Console 端到端验收
企业模拟锁定测试集
```

PENDING 不是通过，只有在实现并运行后才能转为 HARD 或 DIAG。
