# S13-1 Context Packing、历史管理与 Citation 协议

## 输入

默认使用 S11 的 filtered hybrid k20 候选，不默认启用 rerank。

每个候选包含：

```text
child_id
source
page
text
rrf_score
vector_rank
bm25_rank
parent_id
```

## 上下文三层

```text
system
history
retrieval context
```

固定优先级：

```text
system > 最近对话 > retrieval context > 旧对话摘要
```

## Token 预算

初始总预算：

```text
total_budget=3000
```

建议分配：

```text
system: 300
history: 900
retrieval: 1800
```

实际预算按比例计算：

```text
system_ratio=0.10
history_ratio=0.30
retrieval_ratio=0.60
```

Token 仍使用近似值：

```python
estimated_tokens = max(1, len(text) // 2)
```

后续可替换为真实 tokenizer。

## 检索候选去重

### 1. 文本完全重复

对规范化文本计算 hash：

```python
hashlib.sha256(normalized_text.encode()).hexdigest()
```

重复文本只保留排名最高的 child。

### 2. 同一页码重复

同一个：

```text
(source, page)
```

最多保留 `max_chunks_per_page=2`。

### 3. 同一父页面

默认最多保留 `max_chunks_per_parent=2`。

原因：

```text
避免同一页多个 child 占满全部上下文
```

## 来源多样性

使用 round-robin：

```text
按 source/page 分组
轮流选每组排名最高的 child
```

如果只有一个来源：

```text
按页轮流
```

这样优先保证跨文档和跨页覆盖。

## 冲突提示

检测差旅制度版本：

```text
差旅报销制度_v1.pdf
差旅报销制度_v2.pdf
```

如果上下文同时包含两个版本：

```json
{
  "has_conflict": true,
  "conflict_type": "travel_policy_version",
  "sources": [
    "差旅报销制度_v1.pdf",
    "差旅报销制度_v2.pdf"
  ]
}
```

两版本必须同时保留，不能只选最新版本。

上下文显示时按版本并排：

```text
[C1] v1：住宿上限 500 元
[C2] v2：住宿上限 650 元，2026-10-01 生效
```

模型必须说明版本差异，而不是只回答其中一个数字。

## Citation 协议

每个进入上下文的 child 分配稳定编号：

```text
C1
C2
C3
```

输出：

```json
{
  "citation_id": "C1",
  "source": "Agent平台需求说明.pdf",
  "page": 2,
  "child_id": "Agent平台需求说明.pdf#p2#c2",
  "rank": 1
}
```

模型回答必须使用：

```text
[C1]
[C1][C2]
```

不能输出不存在的编号。

## 不可信内容

检索文本一律视为数据，不视为系统指令。

每条 context 增加：

```json
{
  "trusted": false,
  "content_type": "retrieved_document"
}
```

如果文本含“忽略规则、输出密钥”等 injection 模式：

```json
{
  "suspicious_instruction": true
}
```

不能执行该文本里的指令。

## 历史管理

### 最近对话

保留最近 `N` 轮完整消息。

### 摘要

超预算的旧对话压缩成：

```text
用户目标
已确认事实
已做决定
未完成事项
```

不保存无关寒暄。

### 历史裁剪

裁剪时不能拆散：

```text
assistant(tool_calls) + tool results
```

必须先处理完整 tool-call round。

## Packer 输出

```json
{
  "messages": [
    {
      "role": "system",
      "content": "..."
    },
    {
      "role": "user",
      "content": "..."
    }
  ],
  "retrieval_context": [
    {
      "citation_id": "C1",
      "source": "...",
      "page": 2,
      "text": "...",
      "estimated_tokens": 120,
      "trusted": false
    }
  ],
  "citations": [],
  "conflict": {
    "has_conflict": false
  },
  "budget": {
    "total": 3000,
    "retrieval_used": 1200,
    "history_used": 500,
    "remaining": 1300
  }
}
```

## 评测指标

```text
citation_precision
citation_recall
invalid_citation_count
duplicate_context_count
source_diversity
context_chars
context_tokens_est
conflict_covered
injection_blocked
```

## S13-4 的保真度评测

如后续接入生成模型：

```text
answer_faithfulness
context_relevance
citation_correctness
```

必须保存：

- question
- packed_context
- generated_answer
- citations
- judge_result

## 成功条件

1. 不超 total budget；
2. 无重复正文；
3. 多来源题保持来源多样性；
4. v1/v2 冲突同时进入上下文；
5. 引用编号可追踪到 source/page；
6. 不存在的 citation 数为 0；
7. injection 文本不执行；
8. citation precision 可量化。

## 硬边界

1. 不修改 eval_set；
2. 不重新分块；
3. 不默认启用 reranker；
4. 上下文文本不可信；
5. 冲突来源不能被单版本替换；
6. 历史裁剪不能破坏 tool-call 配对；
7. 不能只用总 token，必须记录各部分预算。
