# SourceLedger 基线运行手册

> 任务：A01 盘点项目资产和可运行基线  
> 盘点日期：2026-10-08  
> 盘点时状态：Docker Desktop 守护进程未启动，项目服务未监听端口

---

## 1. 结论

项目源码就是本仓库根目录。

```text
<repo root>/
```

虚拟环境位于仓库根目录的 `.venv`；环境变量模板为仓库根目录的 `.env.example`，复制为 `.env` 后填写。

启动顺序必须是：

```text
Docker Desktop
  -> PostgreSQL + Redis
  -> Alembic 数据库迁移
  -> FastAPI API
  -> React / Vite 前端
```

---

## 2. 当前真实资产

### 2.1 代码

| 资产 | 路径 |
| --- | --- |
| 项目源码 | `<repo root>` |
| API 入口 | `runtime\api\S19_2_app.py` |
| 业务路由 | `runtime\api\S19_4_routes.py` |
| 旧 RAG 实现 | `pdf_rag.py` |
| 当前 Agent 实现 | `agent.py` |
| 前端 | `frontend` |
| 数据库迁移 | `runtime\db\migrations` |
| 韧性配置 | `configs\resilience.json` |

### 2.2 数据

| 资产 | 路径 |
| --- | --- |
| 上传目录 | `uploads` |
| Chroma 向量库 | `chroma_db` |
| 评测语料 | `evaluation\corpus` |
| 评测报告 | `evaluation\reports` |

当前 `uploads` 中可见：

```text
AI应用开发知识手册.pdf
差旅报销制度_v1.pdf
```

完整四份评测语料位于 `evaluation\corpus`：

```text
Agent平台需求说明.pdf
AI应用开发知识手册.pdf
差旅报销制度_v1.pdf
差旅报销制度_v2.pdf
```

`uploads` 与 `evaluation\corpus` 的用途不同，不能混为一谈。

### 2.3 环境

```text
Python: 3.13.9
虚拟环境: <repo root>\.venv
```

虚拟环境中存在：

```text
python.exe
pip.exe
uvicorn.exe
alembic.exe
```

环境变量示例文件包含：

```text
DEEPSEEK_API_KEY
LANGSMITH_TRACING
LANGSMITH_API_KEY
LANGSMITH_PROJECT
DATABASE_URL
DATABASE_ECHO
REDIS_URL
```

不要把真实 `.env` 内容提交到 Git。

---

## 3. 服务与端口

| 服务 | 地址 | 端口 |
| --- | --- | --- |
| PostgreSQL | `localhost:5433` | 本机 `5433` -> 容器 `5432` |
| Redis | `localhost:6380` | 本机 `6380` -> 容器 `6379` |
| FastAPI | `http://127.0.0.1:8000` | `8000` |
| Swagger | `http://127.0.0.1:8000/docs` | `8000` |
| Vite 前端 | `http://127.0.0.1:5173` | `5173` |

2026-10-08 盘点结果：

```text
Docker Desktop daemon: 未运行
5433: 未监听
6380: 未监听
8000: 未监听
5173: 未监听
```

因此当前项目不是运行中状态。

---

## 4. 从零启动步骤

### 4.1 启动 Docker Desktop

先手动启动 Docker Desktop，并等待状态变为 Running。

检查：

```powershell
docker info
```

如果出现：

```text
failed to connect to the docker API
```

说明 Docker Desktop 还没有真正启动，不要继续拉数据库。

### 4.2 启动 PostgreSQL 和 Redis

```powershell
cd <repo root>
docker compose -f .\docker-compose.db.yml up -d
```

检查容器：

```powershell
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
```

预期容器：

```text
agent-runtime-postgres
agent-runtime-redis
```

检查依赖：

```powershell
docker compose -f .\docker-compose.db.yml exec postgres pg_isready -U agent -d agent_runtime
docker compose -f .\docker-compose.db.yml exec redis redis-cli ping
```

预期：

```text
agent_runtime: accepting connections
PONG
```

### 4.3 应用数据库迁移

从仓库根目录执行：

```powershell
cd <repo root>
.\.venv\Scripts\alembic.exe upgrade head
```

注意：

虚拟环境位于仓库根目录的 `.venv`，因此从仓库根执行 `.\.venv\Scripts\...`。

### 4.4 启动 FastAPI

从仓库根目录执行：

```powershell
cd <repo root>
.\.venv\Scripts\python.exe -m uvicorn runtime.api.S19_2_app:app --host 127.0.0.1 --port 8000
```

第一次启动需要加载 SentenceTransformer 和向量依赖，耗时明显高于后续启动。

检查存活：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

检查数据库和 Redis 就绪：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ready
```

只有 `/ready` 返回：

```text
ready=True
database=True
redis=True
```

才能判定 API 可以接业务请求。

### 4.5 启动前端

打开第二个 PowerShell：

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

访问：

```text
http://127.0.0.1:5173
```

PowerShell 执行策略拦截 `npm` 时使用 `npm.cmd`。

---

## 5. 当前真实 `/ask` 调用链

当前链路：

```text
POST /ask
  -> runtime/api/S19_4_routes.py::ask_question
  -> execute_ask
  -> RunStateRepository.create
  -> DatabaseCheckpointer.save
  -> app.state.ask_function
  -> agent.ask
  -> LangGraph Agent
  -> pdf_rag.search_knowledge
  -> Chroma Vector Search
  -> DeepSeek 生成回答
```

当前 `agent.py` 中的检索工具直接调用：

```python
from pdf_rag import search_knowledge as rag_search
```

其底层是：

```text
BAAI/bge-small-zh-v1.5
  -> Chroma collection: docs
  -> cosine distance
  -> top_k=4
  -> threshold=0.5
```

因此当前真实 `/ask` 仍然是纯向量 RAG，不是高级 Hybrid RAG。

当前尚未进入真实 `/ask` 的能力包括：

- BM25。
- RRF Hybrid。
- 条件 Rerank。
- 完整 Metadata Filter。
- Context Packing。
- 冲突处理和版本指令。
- Prompt Injection 隔离。
- 统一 CapabilityEvent。

这是 B 阶段首要修复目标。

---

## 6. 已有评测入口

当前报告目录存在：

```text
evaluation\reports
```

主要报告：

```text
S07_4_canonical_vector_baseline.json
S08_4_bm25_baseline.json
S08_5_vector_vs_bm25.json
S09_4_hybrid_variants.json
S09_5_hybrid_comparison.json
S10_3_multiquery_hybrid.json
S10_5_multiquery_comparison.json
S11_3_filtered_hybrid.json
S11_5_filtered_comparison.json
S12_3_rerank_hybrid.json
S12_5_rerank_comparison.json
S13_4_hybrid_citation.json
S13_5_citation_cost_eval.json
S17_6_fault_injection.json
S18_6_security_regression.json
S19_6_load_test.json
```

不能只相信 README 中的汇总数字。A02 必须重新运行并验证报告。

---

## 7. 已知问题

### 7.1 已修复：启动命令路径

早期版本 README 在切入子目录后使用 `.\.venv\Scripts\...`，与实际虚拟环境位置不符。
现已统一为：从仓库根目录执行命令，虚拟环境位于仓库根目录的 `.venv`。

### 7.2 Docker Desktop 未运行

本次盘点时 Docker daemon 不可访问，数据库和 Redis 均未运行。

### 7.3 `/ask` 与高级 RAG 脱节

高级检索和 Context 能力已经单独实现，但没有接入真实 `/ask` 主链路。

### 7.4 `uploads` 与评测语料不一致

`uploads` 当前只有两个 PDF，完整 46 条评测语料在 `evaluation\corpus`。

### 7.5 压测并非真实大模型压测

`S19_6_load_test` 使用 `fake_ask`，只能证明 API、数据库、Redis、幂等和 Checkpoint，不代表真实模型吞吐。

### 7.6 流式输出不是底层 token stream

当前 SSE 会先取得完整回答，再分片发送。

### 7.7 Hugging Face 离线开关

`agent.py` 和 `pdf_rag.py` 默认设置：

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

如果本机缓存缺少模型，需要先准备缓存，不能直接依赖在线下载。

---

## 8. A01 验收检查表

- [x] 找到真实源码目录。
- [x] 找到虚拟环境。
- [x] 找到根目录 `.env` 和 `.env.example`。
- [x] 找到 FastAPI 入口和业务路由。
- [x] 找到旧 RAG 实现和当前 Agent 实现。
- [x] 找到 PostgreSQL 和 Redis Compose。
- [x] 找到数据库迁移入口。
- [x] 找到前端入口和端口。
- [x] 找到上传目录、Chroma、评测语料和评测报告。
- [x] 确认当前服务未运行。
- [x] 确认真实 `/ask` 仍使用旧纯向量链路。
- [x] 整理从零启动顺序。
- [x] 记录已知问题。

---

## 9. A01 结论

项目具备完整代码、依赖、数据库配置、前端和评测资产，但当前未运行。

基线启动依赖：

```text
Docker Desktop
PostgreSQL 5433
Redis 6380
Alembic
FastAPI 8000
Vite 5173
```

真正需要先处理的产品问题不是“能不能启动”，而是：

```text
真实 /ask 没有接入已经实现的高级 RAG 与 Runtime 能力
```

这是 B 阶段的主要工作。
