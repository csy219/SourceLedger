# S19 最终总结：FastAPI 服务化、并发压测与阶段收尾

## 1. 阶段目标

S19 将 Project A 从本地检索实验升级为可运行的 FastAPI 服务。

实现内容：

- API schema 和契约
- FastAPI app factory
- health 和 readiness
- PDF 上传与索引
- 会话 API
- 任务状态 API
- 问答 API
- SSE 流式问答
- PostgreSQL 持久化
- Redis
- 请求级幂等
- DatabaseCheckpointer
- 并发压测

## 2. API 列表

```text
GET  /health
GET  /ready

POST /documents/upload

POST /sessions
POST /ask
POST /ask/stream
GET  /tasks/{run_id}
```

## 3. 服务结构

```text
FastAPI
  |
  +-- API schemas
  +-- documents router
  +-- runtime router
  +-- stream router
        |
        +--> RunState
        +--> RunStateRepository
        +--> DatabaseCheckpointer
        +--> RequestIdempotencyService
        +--> agent.ask
```

依赖：

```text
PostgreSQL
Redis
Chroma
sentence-transformers
FastAPI
uvicorn
```

## 4. 问答执行链

```text
POST /ask
    |
    v
request_id 幂等检查
    |
    v
创建 RunState
    |
    v
RunStateRepository.create()
    |
    v
DatabaseCheckpointer.save(call_model)
    |
    v
调用 agent.ask()
    |
    v
保存 AskResponse
    |
    v
DatabaseCheckpointer.save(finish)
    |
    v
IdempotencyRepository.complete()
```

重复请求：

```text
相同 request_id
    |
    v
直接返回历史结果
    |
    v
replayed=true
```

## 5. 流式问答

接口：

```text
POST /ask/stream
```

事件：

```text
event: start
event: token
event: citation
event: done
event: error
```

## 6. 并发压测结果

压测参数：

```text
requests=20
concurrency=5
```

结果：

```text
successful=20
failed=0
latency_ms_avg=187.02
latency_ms_p50=135.01
latency_ms_p95=286.89
latency_ms_max=354.09
context_tokens_total=2400
context_tokens_avg=120
estimated_input_cost_usd=0.0
all_passed=True
```

报告：

```text
evaluation/reports/S19_6_load_test.json
```

当前压测使用 fake_ask，不调用真实大模型，因此测的是 API、数据库、Redis、幂等和 Checkpoint 的服务框架性能。

## 7. 已知限制

- 压测没有包含真实模型生成延迟和成本。
- 当前是单服务进程压测，没有加入多 worker 和队列消费测试。
- Redis 锁尚未接入所有业务写路径。
- 上传接口还缺少文件大小限制、病毒扫描和类型内容校验。
- 认证、租户隔离和权限控制仍待后续完善。
- OpenTelemetry、Langfuse 和正式告警尚未接入。
- 流式问答当前先得到完整结果再分片发送，尚未接入底层 LLM token stream。

## 8. 阶段结果

Project A 现在已经可以：

```text
启动 FastAPI 服务
检查依赖 readiness
上传 PDF
建立索引
创建会话
执行幂等问答
持久化 Run 和 Checkpoint
查询任务状态
流式返回回答
进行并发压测
```

M2：可服务化 RAG 应用已经达标。