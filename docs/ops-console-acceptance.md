# SourceLedger Ops Console 验收记录

> 验收日期：2026-10-11  
> 阶段：D08 前端端到端验收  
> 结果：通过
> 前端：`http://127.0.0.1:5173`  
> 后端：`http://127.0.0.1:8000`

## 1. 最终检查

| 项目 | 结果 |
| --- | --- |
| FastAPI health | `ok` |
| FastAPI readiness | `ready=True` |
| PostgreSQL | `True` |
| Redis | `True` |
| Capability 数量 | `12` |
| 前端 HTTP | `200` |
| TypeScript / Vite 构建 | 通过 |
| 桌面截图 | 已生成 |
| 移动端截图 | 已生成 |

## 2. 六个 Tab

```text
Query
Retrieval
Context
Resilience
Security
Runtime
```

每个 Tab 均已接入真实 API 或真实 Capability 结果，不使用固定模拟成功数据。

## 3. 真实路由

```text
GET  /health
GET  /ready
POST /documents/upload
POST /sessions
POST /ask
POST /ask/stream
GET  /tasks/{run_id}
GET  /capabilities
POST /capabilities/{capability_id}/run
GET  /runs/{run_id}/trace
```

## 4. 12 个 Capability

```text
retrieval_hybrid
rerank_comparison
context_packing
retry_backoff
fallback_chain
circuit_breaker
rate_limit
distributed_lock
idempotency
checkpoint_recovery
security_injection
security_no_evidence
```

C07 统一回归结果：

```text
registry_passed=True
all_passed=True
```

## 5. 前端构建

```text
npm.cmd run build
✓ 1585 modules transformed
✓ built in 5.36s
```

产物：

```text
dist/index.html
dist/assets/index-Bogsf53x.css
dist/assets/index-DUG5OGt4.js
```

## 6. 截图

```text
docs/ops-console-desktop.png
docs/ops-console-mobile.png
```

## 7. 页面能力

### Query

- 真实 `/ask`
- Answer
- Citation
- Token
- Latency
- run_id
- Run Trace 时间线

### Retrieval

- Vector
- BM25
- RRF
- After Rerank
- rank / score / source / page

### Context

- 去重
- 页面上限
- Parent 上限
- Token 预算
- Evidence
- Citation
- Conflict
- Injection
- Final Context
- Context Trace

### Resilience

- Retry + Backoff
- Fallback Chain
- Circuit Breaker
- Rate Limit
- Distributed Lock
- Idempotency
- Checkpoint Recovery

### Security

- 直接 / 间接 Injection
- Injection 分类与匹配
- No Evidence
- 拒答原因
- Evidence 数量与最高分

### Runtime

- PostgreSQL Checkpoint
- 版本序列
- 恢复节点
- 恢复后 step_count
- Runtime Trace
- Tool Call 空状态

## 8. 已知限制

- `context_packing` 首次运行需要加载向量模型和 Reranker，耗时会明显高于后续运行。
- 当前生产语料若没有 v2 或 Injection 样本，Conflict 和 Injection 数量会真实显示为 `0`。
- Runtime Recovery 场景当前没有注册 Tool Call，因此 Tool Calls 显示为空。
- 页面验收以构建、HTTP、API、截图和真实能力调用为主，尚未引入 Playwright 自动化视觉回归。
- 截图使用本机 Edge headless 生成，未进行人工色差比对。

## 9. D 阶段结论

D01-D08 已完成。

```text
Ops Console 六 Tab 可用
真实 API 已接入
真实 Trace 可查询
12 个 Capability 可运行
桌面和移动截图已生成
生产构建通过
```

SourceLedger 的第一个可演示版本已经形成。