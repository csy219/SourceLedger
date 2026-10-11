# S08-1 BM25 分词、索引与评分协议

## 目标

实现纯 BM25 关键词检索，与 canonical vector baseline 对比。

保持：

```text
同一 46 条 eval_set
同一 4 份 PDF
同一 semantic child
candidate_k=10
metric_k=4
```

只改变检索信号：

```text
vector_only -> bm25_only
```

## BM25 解决什么问题

向量检索擅长语义相似，但不擅长精确匹配：

```text
user_id
task_id
tool_name
trace
LangSmith
Langfuse
429
5xx
p95
```

BM25 根据词项出现频率和逆文档频率进行排序，能补强：

- 英文变量名；
- 数字；
- 百分比；
- 专有名词；
- 原始关键词。

## 使用同一份 child

BM25 不重新分块：

```text
semantic child
→ 一份用于向量检索
→ 同一份用于 BM25
```

这样比较的是检索算法，不是分块差异。

## 中文 tokenizer

不依赖外部分词库，使用字符级和双字组合。

对：

```text
审计日志字段
```

生成：

```text
审
计
日
志
字
段
审计
计日
日志
志字
字段
```

目的：

1. 保留单字召回；
2. 用 bigram 保留局部词组；
3. 不引入 jieba 等额外依赖；
4. tokenizer 固定后可复现。

## 英文与代码标识符 tokenizer

先转小写，再提取：

```text
[a-zA-Z_][a-zA-Z0-9_]*
```

例如：

```text
user_id
tool_name
LangSmith
bge-small-zh-v1.5
```

生成：

```text
user_id
tool_name
langsmith
bge-small-zh-v1.5
```

同时对下划线分词：

```text
user_id -> user, id
tool_name -> tool, name
```

保留完整标识符和拆分子词，兼顾精确匹配和泛化。

## 数字 tokenizer

提取连续数字和百分比：

```text
90
429
5%
p95
2026-10-01
```

日期也可以补充：

```text
2026
10
01
```

排序评测仍以原始数字 token 为主。

## Token 去重与顺序

BM25 使用词袋，不关心顺序。

每个 child 生成：

```python
{
    "child_id": "...",
    "tokens": ["审", "计", "日志", ...],
}
```

可以保留重复 token 统计词频，不先做去重。

## BM25 参数

初始参数：

```text
k1=1.5
b=0.75
```

含义：

- `k1`：控制词频继续增加时的收益；
- `b`：控制文档长度归一化。

第一阶段不扫描 k1、b，先建立标准 BM25 baseline。

## BM25 分数

每个问题：

```text
query tokens
→ 与每个 child 计算 BM25 分数
→ 按分数降序
→ 取前 candidate_k=10
```

排序规则：

```text
分数越高越相关
```

与向量距离相反。

## 无答案题处理

BM25 没有距离，只有分数。

第一阶段使用：

```text
score_threshold=0.0
```

规则：

```text
如果前 4 个结果分数都 <= 0，认为没有命中
如果存在正分结果，则使用前 4
```

局限：

- 一些无答案题可能和问题共享“什么、多少、怎么”等常见词；
- 仅靠 BM25 分数难以稳定拒答；
- 后续混合检索可以结合向量阈值和 BM25 分数。

## 评分与排名

保持：

```text
source_check=any/all/none
metric_k=4
```

对每个 child 记录：

```text
child_id
source
page
bm25_score
tokens
rank
```

用于：

- 命中标准来源排名；
- 分析关键词是否起作用；
- 后续 Hybrid 融合。

## 新增指标

```text
bm25_retrieval_passed
bm25_hit_at_1
bm25_hit_at_4
bm25_recall_at_4
bm25_mrr
bm25_latency_ms_avg
```

与 canonical vector 使用相同的 46 题。

## 对比重点

重点查看：

1. E33 是否因 `trace`、`user_id`、`tool_name` 等关键词改善；
2. BM25 是否在数字和变量名题上更强；
3. BM25 是否在语义改写题上更弱；
4. 无答案题是否出现新的误召回；
5. BM25 与向量结果是否能互补。

## 硬边界

1. 不修改 semantic child；
2. 不修改 eval_set；
3. 不修改 metric_k；
4. BM25 只作为独立检索器；
5. 不提前做向量和 BM25 融合；
6. 融合放入 S09 Hybrid Retrieval。

## 下一步

S08-2 将实现：

```python
def tokenize(text: str) -> list[str]:
    ...

def tokenize_query(text: str) -> list[str]:
    ...
```
