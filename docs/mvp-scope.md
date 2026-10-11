# SourceLedger 首个可投递版本范围

> 任务：A06 冻结首个可投递版本范围  
> 冻结日期：2026-10-08  
> 版本代号：SourceLedger Internship MVP v1  
> 目标：完成一个可运行、可观察、可复现、可解释、可用于投递的 Verifiable RAG Runtime

---

## 1. 目标岗位

第一版面向：

```text
AI 应用开发实习
RAG / 知识库方向实习
Agent 应用开发实习
Python AI 后端实习
LLM 工程 / 平台实习
```

首要目标：

```text
争取寒假到岗
```

---

## 2. 第一版成功的定义

面试官可以在 30 秒内看懂项目定位，在 5 分钟内运行或观看 Demo，并能够现场验证：

```text
真实高级 RAG
真实 Runtime Trace
真实 Resilience 行为
真实 Security 行为
真实 Checkpoint 恢复
可复现指标
```

第一版不要求成为完整商业产品，但必须摆脱“普通 RAG 聊天 Demo”的印象。

---

## 2.1 两个交付层级

### V0.9 本月投递版

目标：

```text
10-14 个有效工作日内达到可投递状态
```

必须交付：

```text
真实 /ask 使用 Vector + BM25 + RRF + Context Packing + Citation
最小 CapabilityEvent 与 RunTrace
最小 Trace API
Ops Console 的 Query、Retrieval、Context 三个 Tab
README 和中文简历项目描述
首批 15 家投递
```

允许暂时使用：

```text
原 4 份 PDF 和 46 条 core eval
fake_ask 用于 API 压测
本地运行
最小企业演示数据
```

V0.9 不要求：

```text
12 个 Capability 全部完成
六个 Tab 全部完成
企业模拟 50-100 份文档
200 条锁定测试集
Demo 视频
英文简历
```

### V1.0 完整体现版

在持续投递和面试期间完成：

```text
完整 Resilience 与 Security 可视化
Runtime 状态机与恢复演示
12 个 Capability
六个 Tab
企业模拟数据与锁定测试集
Demo 视频
英文简历
面试反馈闭环
```

V0.9 以“尽快进入招聘流程”为第一目标。  
V1.0 以“提高面试通过率和技术展示完整度”为第一目标。

以下第 3 节 `Must` 默认属于 V1.0 完整范围；V0.9 只执行第 2.1 节列出的子集。

---

## 3. Must：没有它就不能投递

### M01 真实 `/ask` 接入高级 RAG

对应计划：

```text
B01-B10
```

必须实现：

```text
Query Rewrite
Metadata Filter
Vector Search
BM25 Search
RRF Hybrid
Context Packing
Citation
Conflict
Injection Marking
DeepSeek 生成
```

验收：

```text
真实 /ask 请求可以观察到完整阶段
模型实际证据 = Context evidence = 最终 citations
```

### M02 Rerank 可关闭且条件触发

对应计划：

```text
B05
```

必须实现：

```text
默认关闭
配置可开启
保留开启前后排名和延迟对比
```

不要求 Rerank 必须提升所有质量指标，但要求行为可解释、可复现。

### M03 统一 CapabilityEvent 与 RunTrace

对应计划：

```text
C01-C03
```

必须实现：

```text
event_id
run_id
stage
operation
status
attempt
action
duration_ms
metadata
```

验收：

```text
成功请求 trace 完整率 100%
run_id 一致
event_id 唯一
```

### M04 12 个能力场景可运行

对应计划：

```text
C04-C07
```

必须覆盖：

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

每个场景必须有：

```text
输入
执行事件
最终状态
错误或成功原因
测试
```

### M05 Ops Console 六个 Tab

对应计划：

```text
D01-D08
```

必须包含：

```text
Query
Retrieval
Context
Resilience
Security
Runtime
```

硬要求：

```text
真实数据
真实事件
无固定模拟结果
无 console error
桌面与移动端不重叠
```

### M06 基线评测不回退

对应计划：

```text
A02、A05
```

硬门槛：

```text
Hybrid Hit@1 >= 0.9500
Hybrid Recall@4 >= 0.9700
Hybrid MRR >= 0.9700
Hybrid nDCG@4 >= 0.9600
invalid citation = 0
citation recall = 1.0
conflict = 3/3
injection = 2/2
budget violation = 0
```

### M07 Runtime、幂等和恢复可用

对应计划：

```text
A03、C05
```

必须证明：

```text
重复 request_id 只执行一次
成功请求至少产生 starting/finishing checkpoint
进程中断后可以从 checkpoint 识别恢复点
失败状态落库
```

### M08 Resilience 与 Security 回归通过

对应计划：

```text
C05-C07
```

必须满足：

```text
故障注入 = 4/4
安全回归 = 5/5
secret leak = 0
unsafe tool execution = 0
```

### M09 企业模拟数据最小集

对应计划：

```text
E07-E09
```

最低要求：

```text
>= 30 份公开文档
>= 120 条标注问题
>= 5 类场景
dev/test 分离
独立 collection
不污染原 46 条评测
```

必须覆盖：

```text
多来源
多版本
跨文档多跳
时效
无答案
Injection
```

### M10 企业模拟评测报告

对应计划：

```text
E11
```

必须输出：

```text
Hit@k
Recall@k
MRR
nDCG
回答正确率
Citation Precision
Citation Recall
无答案拒答率
冲突覆盖率
Injection 隔离率
延迟
Token 成本
```

### M11 GitHub 首页可读

对应计划：

```text
F01-F02
```

README 必须包含：

```text
项目定位
核心差异
架构图
真实链路
指标
启动命令
Demo
已知限制
```

### M12 中文简历和投递

对应计划：

```text
F03、F05
```

必须完成：

```text
中文简历项目描述
至少 15 家目标岗位投递
投递记录表
```

---

## 4. Should：明显增强竞争力

### S01 企业模拟语料扩展到完整版本

目标：

```text
50-100 份文档
200+ 条问题
```

### S02 Demo 视频

目标：

```text
3-5 分钟
包含正常问答、Trace、检索对比、故障恢复和安全
```

### S03 英文简历

```text
与中文版本事实一致
英文表达可被招聘方快速扫描
```

### S04 一键启动

```text
PowerShell 或 Makefile
检查 Docker
启动 DB/Redis
迁移
启动 API
启动前端
```

### S05 评测报告网页化

```text
把 JSON 和 Markdown 指标展示到 Ops Console
支持查看历史版本
```

### S06 真实条件 Rerank

```text
低置信度或歧义问题才开启
展示延迟与质量收益
```

### S07 面试问答手册

```text
10 个项目追问
10 个 RAG 追问
10 个 Runtime/可靠性追问
```

---

## 5. Later：明确延后

以下内容不进入首个投递版本：

```text
多租户
完整 RBAC 和 SSO
Kubernetes
服务网格
多区域部署
自动扩容
Qdrant / Milvus 迁移
模型微调
训练自己的 Reranker
复杂 MCP 工具市场
MCP Server 集群
完整 Coding Agent
RepoFix 自动修复仓库
浏览器自动化 Agent
多 Agent 自主协作平台
移动 App
```

延后不代表永不实现，只是不能阻塞第一版投递。

---

## 6. 明确不做

首个版本不做：

```text
上传真实公司机密资料
使用版权不明语料
声称支持全部文档格式
伪造企业客户或生产规模
把 fake_ask 压测写成真实模型压测
用静态前端数据冒充真实执行
把计划能力写成已完成能力
```

---

## 7. 功能进入真实 `/ask` 与独立 Demo 的边界

### 必须进入真实 `/ask`

```text
Query Rewrite
Metadata Filter
Vector
BM25
RRF
Context Packing
Citation
Conflict
Injection Marking
DeepSeek
CapabilityEvent
RunTrace
```

### 可以独立触发并展示

```text
timeout
retry
fallback
circuit breaker
rate limit
distributed lock
idempotency
checkpoint recovery
危险工具拦截
```

原因：

这些能力需要故障注入才能稳定演示，不应为了演示而故意破坏真实问答。

### 必须既进入真实链路又独立可触发

```text
idempotency
checkpoint
security injection
no-evidence
```

---

## 8. 投递最低交付线

达到以下条件才允许把项目作为主项目投递：

```text
M01-M08 全部完成
M09 达到最小企业模拟集
M10 报告可复现
M11 README 完整
M12 中文简历和 15 家投递完成
```

视频、英文简历、完整企业数据集属于增强项，可以在首批投递后继续补。

---

## 9. 实施顺序

```text
1. B01-B10 高级 RAG 主链路
2. C01-C03 事件、Trace 和 API
3. C04-C07 12 个能力
4. D01-D08 Ops Console
5. E07-E11 企业模拟数据与评测
6. F01-F03 README 与中文简历
7. F05 首批 15 家投递
8. E04-E06、F04 做增强
9. 根据面试反馈补 Gap
```

---

## 10. 变更控制

任何新需求加入首版前必须回答：

```text
1. 它是否直接提高获得实习的概率？
2. 它是否能进入真实链路或现场 Demo？
3. 它是否能提供可复现证据？
4. 它会替换或延后现有哪一项？
5. 它是否影响首批投递时间？
```

如果新增需求不能替换或延后其他内容，则不进入第一版。

同一时间最多推进：

```text
一个核心实现任务
一个证据或材料任务
持续投递跟进
```

---

## 11. 完成定义

SourceLedger Internship MVP v1 完成必须同时满足：

```text
从一条命令可以启动
真实 /ask 使用高级 RAG
12 个能力有真实事件
六个 Tab 有真实可视化
基线指标不回退
企业模拟评测可复现
安全与故障回归通过
GitHub README 可读
Demo 或录屏可用
中文简历可投递
至少 15 家投递完成
```

任何一项只有文档描述、没有命令或报告，都不算完成。

---

## 12. 范围冻结结论

首版目标是：

```text
能做、能跑、能看、能证明、能解释、能投递
```

不是：

```text
功能越多越好
概念越高级越好
部署越复杂越好
```

所有后续任务必须服从这份范围。
