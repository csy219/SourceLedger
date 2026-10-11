# SourceLedger 旧向量检索入口与替换地图

> 任务：A04 找到旧纯向量链路的所有入口  
> 盘点日期：2026-10-08  
> 目标：识别 `pdf_rag + Chroma` 的所有调用点，并制定安全替换顺序

---

## 1. 结论

旧向量检索核心集中在一个模块：

```text
project_a\pdf_rag.py
```

它同时承担了四类职责：

```text
PDF 解析
文本分块
BGE 向量化
Chroma 持久化与检索
```

真实 `/ask` 只有一个检索工具调用入口：

```text
agent.py -> pdf_rag.search_knowledge
```

但 `pdf_rag` 还被上传 API、评测脚本和历史实验大量直接导入。

因此不能直接删除或整体重写 `pdf_rag.py`。正确策略是：

```text
保留兼容层
-> 新建检索抽象
-> 生产 /ask 切换到高级 RAGRuntime
-> 评测和历史实验继续使用旧接口直到逐个迁移
```

---

## 2. 旧实现核心模块

文件：

```text
project_a\pdf_rag.py
```

### 2.1 常量

| 符号 | 行号 | 用途 |
| --- | ---: | --- |
| `BASE_DIR` | 17 | 当前项目根目录 |
| `UPLOAD_DIR` | 18 | 上传文件目录 |
| `CHROMA_DIR` | 22 | Chroma 持久化目录 |
| `MODEL_NAME` | 23 | `BAAI/bge-small-zh-v1.5` |

### 2.2 全局状态

```text
_model
_client
_collection
_collection_lock
```

### 2.3 核心函数

| 函数 | 行号 | 职责 |
| --- | ---: | --- |
| `get_model()` | 27 | 懒加载 SentenceTransformer |
| `embed()` | 35 | 文本向量化 |
| `chunk_text()` | 43 | 固定字符分块 |
| `load_pdf_pages()` | 54 | PDF 按页提取文本 |
| `get_collection()` | 68 | 获取 Chroma `docs` 集合 |
| `index_pdf()` | 83 | 解析、分块、向量化、入库 |
| `search_knowledge()` | 103 | 纯向量检索 |

### 2.4 当前检索参数

```text
top_k=4
threshold=0.5
collection=docs
space=cosine
```

---

## 3. 生产链路入口

### 3.1 真实 Agent 检索工具

文件：

```text
project_a\agent.py
```

导入：

```python
from pdf_rag import search_knowledge as rag_search
```

行号：

```text
agent.py:20
```

第一次调用，用于 Agent Tool：

```python
hits = rag_search(query, top_k=4, threshold=0.5)
```

行号：

```text
agent.py:32
```

工具注册：

```text
agent.py:46
agent.py:62
```

第二次调用，用于构造 citations：

```python
hits = rag_search(question, top_k=4, threshold=0.5)
```

行号：

```text
agent.py:81
```

影响：

```text
P0
```

这是真实 `/ask` 替换高级 RAG 的第一关键文件。

### 3.2 文档上传与索引

文件：

```text
project_a\runtime\api\S19_3_documents.py
```

导入：

```python
from pdf_rag import UPLOAD_DIR, index_pdf
```

行号：

```text
S19_3_documents.py:57
```

用途：

```text
POST /documents/upload
-> 保存 PDF
-> index_pdf
-> Chroma docs
```

影响：

```text
P0
```

替换高级 RAG 时要在此处接入新的 IndexingPipeline，但初期可以继续复用 `index_pdf`。

### 3.3 旁路旧 FastAPI 服务

文件：

```text
project_a\app.py
```

导入：

```python
from agent import ask
from pdf_rag import UPLOAD_DIR, index_pdf
```

行号：

```text
app.py:6
app.py:7
```

接口：

```text
GET  /health
POST /upload
POST /ask
```

特点：

```text
没有 RunState
没有 Checkpoint
没有幂等
没有标准 AskResponse
```

当前 S19 主入口是：

```text
runtime.api.S19_2_app:app
```

因此 `project_a\app.py` 应视为旧版旁路入口，不参与后续主链路升级。

---

## 4. 评测与消融入口

这些文件依赖 `pdf_rag` 的底层能力，但不应在 B 阶段一次性全部重写。

### 4.1 PDF 结构检查

```text
evaluation\inspect_pdf_structure.py
```

导入：

```python
from pdf_rag import load_pdf_pages
```

用途：

```text
PDF 结构分析
```

影响：

```text
P2
```

### 4.2 固定分块基线

```text
evaluation\run_fixed_chunk_baseline.py
```

导入：

```python
from pdf_rag import chunk_text, embed, load_pdf_pages
```

同时直接使用：

```text
chromadb.PersistentClient
chromadb.Collection
```

用途：

```text
固定分块、建库、检索、指标评测
```

影响：

```text
P1
```

### 4.3 Block 相似度检查

```text
evaluation\S05_1_inspect_block_similarity.py
```

导入：

```text
embed
load_pdf_pages
```

影响：

```text
P2
```

### 4.4 语义分块

```text
evaluation\S05_2_semantic_chunking.py
```

导入：

```text
embed
load_pdf_pages
```

影响：

```text
P1
```

### 4.5 parent-child 索引

```text
evaluation\S06_2_parent_child_index.py
```

导入：

```text
embed
load_pdf_pages
```

同时直接使用 Chroma。

影响：

```text
P1
```

### 4.6 Semantic Vector Sweep

```text
evaluation\S07_2_semantic_vector_sweep.py
```

直接使用：

```text
chromadb.PersistentClient
get_collection
```

影响：

```text
P1
```

### 4.7 Hybrid 评测

```text
evaluation\S09_4_hybrid_eval.py
```

导入：

```text
embed
```

同时直接使用 Chroma。

影响：

```text
P1
```

### 4.8 Filtered Hybrid

```text
evaluation\S11_3_filtered_hybrid.py
```

导入：

```text
embed
```

并通过 Chroma 的 `where` 条件实现 metadata filter。

影响：

```text
P1
```

### 4.9 Hybrid Citation

```text
evaluation\S13_4_hybrid_citation.py
```

直接使用：

```text
chromadb.PersistentClient
get_collection
```

影响：

```text
P1
```

### 4.10 Harness

Harness runner 通过独立 collection 和 Chroma 客户端运行。

涉及目录：

```text
evaluation\harness
```

替换时应保证新检索抽象能输出同样指标，而不是马上删除旧评测。

---

## 5. 文档和历史引用

以下文件出现旧检索名称，但不参与运行时：

```text
README.md
README.old.md
docs\architecture.md
docs\baseline-runbook.md
docs\current-ask-trace.md
runtime\api\S19_final_notes.md
```

处理策略：

```text
最后统一更新
不要在代码尚未切换时提前宣称已经完成
```

---

## 6. 全部 Python 导入点

完整导入清单：

```text
agent.py
app.py
evaluation\inspect_pdf_structure.py
evaluation\run_fixed_chunk_baseline.py
evaluation\S05_1_inspect_block_similarity.py
evaluation\S05_2_semantic_chunking.py
evaluation\S06_2_parent_child_index.py
evaluation\S09_4_hybrid_eval.py
evaluation\S11_3_filtered_hybrid.py
runtime\api\S19_3_documents.py
```

所有 `search_knowledge/rag_search` 调用：

```text
agent.py:32
agent.py:81
pdf_rag.py:103 定义
```

结论：

```text
真实 /ask 的检索替换面很小
底层索引和评测依赖面很大
```

---

## 7. 建议的新结构

不要继续把所有能力堆进 `pdf_rag.py`。

建议新增：

```text
runtime\retrieval\contracts.py
runtime\retrieval\vector_store.py
runtime\retrieval\bm25.py
runtime\retrieval\rrf.py
runtime\retrieval\reranker.py
runtime\retrieval\indexing.py
runtime\rag_runtime.py
```

职责：

| 模块 | 职责 |
| --- | --- |
| `contracts.py` | RetrievalHit、RetrievalResult、Filter |
| `vector_store.py` | 封装 Chroma 查询 |
| `bm25.py` | BM25 候选 |
| `rrf.py` | Vector + BM25 融合 |
| `reranker.py` | 条件重排 |
| `indexing.py` | 文档解析、分块、向量化、入库 |
| `rag_runtime.py` | 编排完整高级 RAG |

---

## 8. 安全替换顺序

### Step 1：定义稳定返回契约

保持旧 hits 字段可用：

```text
text
source
page
distance
```

新增字段：

```text
chunk_id
vector_rank
vector_score
bm25_rank
bm25_score
rrf_score
rerank_score
metadata
```

### Step 2：封装旧 Vector

将 `pdf_rag.search_knowledge` 包装为：

```text
VectorRetriever.search()
```

行为不变，先保证结果等价。

### Step 3：接入 BM25 与 RRF

实现：

```text
VectorRetriever + BM25Retriever -> RRF
```

通过评测确认不回归。

### Step 4：接入 Context Packing

将 RRF 候选送入现有：

```text
pack_context
build_agent_context
```

统一 Citation ID。

### Step 5：建立 RAGRuntime

输入：

```text
question
thread_id
run_id
filters
history
budget
```

输出：

```text
answer
citations
evidence
usage
trace
```

### Step 6：替换 Agent Tool

将：

```text
agent.search_knowledge -> pdf_rag.search_knowledge
```

替换为：

```text
agent.search_knowledge -> RAGRuntime.retrieve
```

不要同时删除旧函数。

### Step 7：消除第二次检索

删除 `agent.py:81` 为 citations 单独执行的检索。

citations 必须直接使用 RAGRuntime 产生的证据。

### Step 8：替换上传索引

`S19_3_documents.py` 改为调用新的 IndexingPipeline。

迁移期可保留：

```text
新 pipeline 成功 -> 使用新索引
新 pipeline 失败 -> 临时回退 index_pdf
```

### Step 9：逐个迁移评测

优先级：

```text
S13_4
S11_3
S09_4
S07_2
S06_2
S05_2
run_fixed_chunk_baseline
```

历史报告和 baseline 不修改。

### Step 10：最后更新文档

所有指标和链路真实跑通后，再修改：

```text
README.md
architecture.md
```

---

## 9. 必须修改与可以保留

### P0 必须修改

```text
agent.py
runtime\rag_runtime.py 或 rag_service.py
runtime\api\S19_2_app.py 注入
runtime\api\S19_4_routes.py 返回证据与 trace
```

### P0 兼容修改

```text
runtime\api\S19_3_documents.py
```

### P1 后续迁移

```text
evaluation\S13_4_hybrid_citation.py
evaluation\S11_3_filtered_hybrid.py
evaluation\S09_4_hybrid_eval.py
evaluation\S07_2_semantic_vector_sweep.py
evaluation\S06_2_parent_child_index.py
evaluation\S05_2_semantic_chunking.py
evaluation\run_fixed_chunk_baseline.py
```

### P2 保留

```text
pdf_rag.py
app.py
历史消融脚本
baseline 报告
```

`pdf_rag.py` 在迁移期内继续作为：

```text
向量索引适配器
BM25 可复用语料来源
兼容 fallback
```

---

## 10. 风险清单

### 风险 1：索引结构不兼容

当前 Chroma metadata 只有：

```text
source
page
```

高级 RAG 需要：

```text
chunk_id
parent_id
document_id
version
department
permission
updated_at
content_type
```

处理：

```text
新增索引 schema
不要直接覆盖旧的 docs collection
```

### 风险 2：Citation 证据变化

替换后必须确保：

```text
模型实际使用的证据
=
最终 citations
```

### 风险 3：评测数据污染

处理：

```text
原 46 条 core eval 不动
企业模拟数据使用独立 collection
```

### 风险 4：一次替换过多入口

处理：

```text
先生产 RAGRuntime
再逐层接工具、API、评测
```

---

## 11. A04 结论

旧向量链路的真正生产入口只有：

```text
agent.py
S19_3_documents.py
```

其中 `/ask` 的核心风险点是 `agent.py` 的两次 `rag_search` 调用。

评测与历史实验虽然大量依赖 `pdf_rag`，但不阻塞生产链路升级。

推荐第一家提交的改动范围：

```text
新增 runtime\retrieval\*
新增 runtime\rag_runtime.py
修改 agent.py
修改 S19_2_app.py 注入
修改 S19_4_routes.py 返回结构
```

不要第一步重写所有评测脚本，也不要删除 `pdf_rag.py`。
