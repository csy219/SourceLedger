# SourceLedger 当前 `/ask` 真实请求链路

> 任务：A03 画出当前真实请求链路  
> 盘点日期：2026-10-08  
> 范围：`POST /ask` 当前实际执行路径  
> 结论：Runtime 持久化和幂等已接入，但检索仍是旧纯向量 RAG

---

## 1. 当前真实链路总览

```text
HTTP POST /ask
  -> FastAPI app
  -> S19_4_routes.ask_question
  -> execute_ask
  -> RequestIdempotencyService.execute
  -> RunState.create
  -> RunStateRepository.create
  -> DatabaseCheckpointer.save(node="call_model")
  -> app.state.ask_function
  -> agent.ask
  -> LangGraph
  -> DeepSeek 工具决策
  -> search_knowledge tool
  -> pdf_rag.search_knowledge
  -> SentenceTransformer BAAI/bge-small-zh-v1.5
  -> Chroma collection "docs"
  -> ToolNode 返回检索文本
  -> DeepSeek 生成最终回答
  -> agent.ask 再执行一次向量检索生成 citations
  -> DatabaseCheckpointer.save(node="finish")
  -> AskResponse
```

当前链路不是高级 RAG：

```text
没有 BM25
没有 RRF Hybrid
没有 Metadata Filter
没有 Rerank
没有 Context Packing
没有 Conflict Guard
没有 Injection Guard
没有 Rate Limit
没有 Circuit Breaker
没有 Fallback
没有真实模型 Tool-call 级 Checkpoint
```

---

## 2. HTTP 请求入口

接口：

```text
POST /ask
```

定义位置：

```text
runtime\api\S19_4_routes.py
```

处理函数：

```text
ask_question
```

开始行：

```text
S19_4_routes.py:245
```

请求模型：

```text
runtime\api\S19_1_schemas.py::AskRequest
```

字段：

```text
question
thread_id
request_id
stream
```

响应模型：

```text
runtime\api\S19_1_schemas.py::AskResponse
```

主要字段：

```text
run_id
thread_id
status
answer
citations
context_tokens_est
input_tokens
output_tokens
total_tokens
cache_read_tokens
latency_ms
replayed
```

---

## 3. FastAPI 启动与依赖注入

入口：

```text
runtime\api\S19_2_app.py
```

应用创建：

```text
create_app()
```

生命周期：

```text
lifespan()
```

启动时依次初始化：

1. `DatabaseConfig.from_env()`
2. `create_db_engine()`
3. `create_session_factory()`
4. `app.state.ask_function`
5. Redis 客户端
6. `app.state.engine`
7. `app.state.redis`

### 3.1 问答函数注入

如果存在：

```text
app.state.ask_function_override
```

则使用测试或外部注入函数。

否则：

```python
from agent import ask as agent_ask
app.state.ask_function = agent_ask
```

真实服务默认使用：

```text
agent.ask
```

### 3.2 数据库

数据库引擎由：

```text
runtime\db\engine.py::create_db_engine
```

创建。

Session 工厂由：

```text
runtime\db\engine.py::create_session_factory
```

创建。

### 3.3 Redis

Redis 通过：

```text
runtime\api\S19_2_app.py::get_redis_url
Redis.from_url
```

初始化。

但当前 `/ask` 主流程没有直接使用 `app.state.redis`。  
Redis 目前主要用于 readiness 和其他独立韧性能力，没有接入问答主链路。

---

## 4. 请求级业务执行

核心函数：

```text
runtime\api\S19_4_routes.py::execute_ask
```

开始行：

```text
S19_4_routes.py:81
```

### 4.1 创建依赖

`get_repositories()` 创建：

```text
RunStateRepository
DatabaseCheckpointer
RequestIdempotencyService
```

对应代码：

```text
S19_4_routes.py:50
```

### 4.2 计算幂等键

```python
request_key = ask_request.request_id or uuid.uuid4().hex
```

含义：

- 客户端传了 `request_id`：同一个 ID 只执行一次。
- 客户端没传：每次请求生成随机键，不会命中幂等重放。

### 4.3 封装业务函数

真实执行逻辑被封装为：

```text
business_function
```

它是幂等服务唯一会执行的业务入口。

---

## 5. 幂等链路

入口：

```text
runtime\resilience\S17_5_idempotency.py::RequestIdempotencyService.execute
```

开始行：

```text
S17_5_idempotency.py:131
```

调用于：

```text
S19_4_routes.py:197
```

执行顺序：

```text
1. repository.begin(key, run_id)
2. 如果 created=True，执行新的 business_function
3. 如果 created=False，读取已有记录
4. SUCCEEDED -> 直接返回历史结果，replayed=True
5. STARTED -> 抛出 RequestInProgress
6. FAILED -> 默认抛出失败错误
7. 新请求成功后 repository.complete 保存结果
```

仓储：

```text
runtime\db\S16_4_idempotency_repository.py::IdempotencyRepository
```

`begin()` 使用数据库主键和提交冲突保证并发下只创建一个请求记录。

### 当前语义问题

`execute_ask` 当前调用：

```python
idempotency_service.execute(
    key=request_key,
    run_id=ask_request.thread_id,
    func=business_function,
)
```

这里传入的是 `thread_id`，并不是后面真实生成的 `RunState.run_id`。

因此：

- 幂等记录里的 run_id 实际代表 thread_id。
- RunState 另有真实 run_id。
- 两者语义不一致，后续应统一。

---

## 6. RunState 生命周期

模型：

```text
runtime\S15_state_reference.py::RunState
```

开始行：

```text
S15_state_reference.py:222
```

创建：

```python
state = RunState.create(
    thread_id=ask_request.thread_id,
    goal=ask_request.question,
    max_steps=20,
)
```

创建后默认：

```text
status = pending
current_node = start
step_count = 0
max_steps = 20
```

当前 `/ask` 手工执行的状态转换：

```text
pending
  -> running
  -> completed
```

失败支路：

```text
running
  -> failed
```

当前 `/ask` 只执行一次：

```text
state.increment_step()
```

因此 `step_count` 当前始终只记录到 1，不能代表 LangGraph 内部真实执行步数。

---

## 7. Run 与 Checkpoint 持久化

### 7.1 创建 Run 主记录

```text
runtime\db\S16_3_run_repository.py::RunStateRepository.create
```

开始行：

```text
S16_3_run_repository.py:91
```

写入字段：

```text
run_id
thread_id
goal
status
current_node
step_count
max_steps
```

### 7.2 第一次 Checkpoint

调用：

```python
checkpointer.save(state, node="call_model")
```

发生在：

```text
调用 agent.ask 之前
```

写入内容：

```text
完整 RunState 快照
Checkpoint 版本
node
run 主表状态冗余字段
```

### 7.3 第二次 Checkpoint

成功时：

```python
checkpointer.save(state, node="finish")
```

失败时：

```python
checkpointer.save(state, node="failed")
```

仓储：

```text
runtime\db\checkpointer.py::DatabaseCheckpointer.save
```

开始行：

```text
checkpointer.py:53
```

设计：

- 对 Run 主记录使用行锁。
- 计算该 run 的下一个 checkpoint 版本。
- 存储完整 `state_snapshot`。
- 同步更新 Run 主表的 `status/current_node/step_count`。

### 7.4 LangGraph 自己的 Checkpointer

`agent.py` 还使用了：

```text
langgraph.checkpoint.memory.InMemorySaver
```

它与 `DatabaseCheckpointer` 不是同一个系统。

当前存在双状态：

```text
API 层 RunState + PostgreSQL Checkpoint
LangGraph InMemorySaver
```

结果是：

- API 任务状态可以持久化。
- LangGraph 对话状态只在进程内存中。
- 进程重启后，API 能看到 RunState，但 LangGraph 图状态会丢失。
- 当前没有从 PostgreSQL 真正恢复并继续 LangGraph 执行。

---

## 8. Agent 与工具调用

入口：

```text
agent.py::ask
```

开始行：

```text
agent.py:72
```

### 8.1 模型

```text
ChatOpenAI
model=deepseek-v4-flash
base_url=https://api.deepseek.com
temperature=0
max_tokens=2000
```

### 8.2 Graph

节点：

```text
agent
tools
```

结构：

```text
START -> agent
agent -> tools 或 END
tools -> agent
```

### 8.3 工具

LangChain tool：

```text
agent.py::search_knowledge
```

真实执行：

```python
hits = rag_search(query, top_k=4, threshold=0.5)
```

对应：

```text
agent.py:32
```

### 8.4 工具结果

工具把命中片段拼为文本：

```text
[文件名 第X页] 正文
```

没有结构化 metadata，也没有统一 CapabilityEvent。

---

## 9. 旧向量检索

实现：

```text
pdf_rag.py::search_knowledge
```

开始行：

```text
pdf_rag.py:103
```

模型：

```text
BAAI/bge-small-zh-v1.5
```

向量库：

```text
Chroma PersistentClient
path=chroma_db
collection=docs
```

检索：

```text
embed(query)
-> Chroma query
-> cosine distance
-> top_k=4
-> distance < 0.5
```

返回：

```text
text
source
page
distance
```

### 当前实际特性

```text
普通 Vector Search
参数固定
无 BM25
无 RRF
无条件 Rerank
无 metadata filter
无 query rewrite
```

---

## 10. Citation 的真实来源

这是一个重要问题。

模型生成最终回答时使用的证据来自 Graph 内的 `search_knowledge` 工具调用。

但 `agent.ask` 在 Graph 结束后又单独执行了一次：

```python
hits = rag_search(question, top_k=4, threshold=0.5)
```

然后直接把这些 hits 作为 citations 返回。

因此当前 citations：

- 来自第二次独立检索。
- 不一定与模型实际使用的工具调用上下文完全一致。
- 没有保存模型实际看到的 citation ID。
- 没有验证回答中的 `[C1]` 是否真的对应最终 citations。

后续真实 RAGRuntime 必须让检索、Context Packing、模型输入和 Citation 使用同一份证据。

---

## 11. 响应组装

`execute_ask` 从 `raw_result` 取：

```text
answer
citations
context_tokens_est
input_tokens
output_tokens
total_tokens
cache_read_tokens
latency_ms
```

然后构造：

```text
AskResponse
```

幂等重放时：

```text
replayed=True
```

首次执行时：

```text
replayed=False
```

---

## 12. 当前链路数据流

```text
AskRequest
  |
  v
request_key = request_id or uuid
  |
  v
IdempotencyRepository.begin
  |
  +--> existing SUCCEEDED -> 返回历史 AskResponse
  |
  v
RunState.create -> pending
  |
  v
RunStateRepository.create -> PostgreSQL runs
  |
  v
status=running, node=call_model, step_count=1
  |
  v
DatabaseCheckpointer.save -> checkpoint v1
  |
  v
agent.ask(question, thread_id)
  |
  v
LangGraph + DeepSeek
  |
  +--> tool call: search_knowledge(query)
  |      |
  |      v
  |    pdf_rag.search_knowledge
  |      |
  |      v
  |    bge-small-zh-v1.5 -> Chroma docs
  |
  v
DeepSeek final answer
  |
  v
再次 rag_search(question) -> citations
  |
  v
status=completed, node=finish
  |
  v
DatabaseCheckpointer.save -> checkpoint v2
  |
  v
IdempotencyRepository.complete
  |
  v
AskResponse
```

---

## 13. 当前已经接入 `/ask` 的能力

```text
FastAPI 请求校验
统一响应模型
请求级幂等
RunState
PostgreSQL Run 主记录
PostgreSQL Checkpoint
失败状态落库
LangGraph Agent
DeepSeek
纯向量检索
Citation 基础返回
Token usage
Latency
```

---

## 14. 当前仍未接入 `/ask` 的能力

### 检索层

```text
Query Rewrite
Metadata Filter
BM25
RRF Hybrid
条件 Rerank
Parent-child 上下文扩展
```

### Context 层

```text
去重
页面/父级限额
round-robin
来源多样性
Token 预算
统一 Citation ID
冲突提示
Injection 隔离
```

### Runtime 层

```text
真实 ToolCallRecord 注册
工具级幂等
Graph 级持久化恢复
统一 CapabilityEvent
Run Trace
当前真实节点粒度
```

### Resilience 层

```text
真实 timeout
真实 retry/backoff
模型 fallback
检索 fallback
circuit breaker
local rate limit
Redis rate limit
distributed lock
```

### Security 层

```text
直接 Prompt Injection Guard
间接 Prompt Injection Guard
无证据拒答
伪造 Citation 检查
危险工具策略
权限边界
```

---

## 15. 目标高级 RAG 链路

后续 B 阶段目标：

```text
POST /ask
  -> FastAPI
  -> RAGRuntime
  -> Query Rewrite
  -> Metadata Filter
  -> Vector + BM25
  -> RRF Hybrid
  -> 条件 Rerank
  -> Context Packing
  -> Citation / Conflict / Injection
  -> DeepSeek Generation
  -> Answer + Evidence + Usage + Trace
```

同时接入：

```text
CapabilityEvent
RunTrace
timeout
retry/backoff
fallback
circuit breaker
rate limit
idempotency
checkpoint recovery
security guard
```

目标原则：

```text
模型实际使用的证据
=
最终返回的 citations
=
Trace 中记录的证据
```

---

## 16. 当前与目标链路对比

| 阶段 | 当前真实链路 | 目标链路 |
| --- | --- | --- |
| Query 输入 | 原问题 | Query Rewrite |
| 过滤 | 无 | Metadata Filter |
| Vector | 有 | 有 |
| BM25 | 无 | 有 |
| 融合 | 无 | RRF |
| Rerank | 无 | 条件触发 |
| Context 组装 | 工具文本直接拼接 | Context Packing |
| Citation | 第二次检索结果 | 与模型证据一致 |
| 冲突 | 无 | Conflict Guard |
| Injection | 无 | Injection Guard |
| 状态 | RunState + DB Checkpoint | 统一 Runtime Trace |
| 弹性 | 无 | timeout/retry/fallback/breaker |
| 限流与锁 | 未接入 | Redis/local |
| 可观测性 | 基础字段 | 分阶段 CapabilityEvent |

---

## 17. A03 结论

当前 `/ask` 是一个“具备数据库状态和请求幂等的普通纯向量 RAG Agent”。

它已经具备真实服务化和任务状态持久化，但高级检索、Context Packing、Resilience 和 Security 仍然主要是独立模块或评测能力，没有进入真实回答链路。

因此 B 阶段不能只加新模块，必须完成：

```text
高级检索能力
-> 真实 RAGRuntime
-> 真实 /ask
-> 同一份证据
-> 统一事件
-> 前端可观察
```

这份文档描述的是当前现状，不代表目标能力已经完成。
