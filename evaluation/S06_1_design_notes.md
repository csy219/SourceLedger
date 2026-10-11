# S06-1 Parent-child / small-to-big 设计

## 目标

使用小块负责高精度向量召回，命中后返回更大的父块上下文。

流程：

```text
问题
→ 在 child 小块中检索
→ 得到命中的 child
→ 根据 child.parent_id 找到 parent
→ 返回 parent 文本作为回答上下文
→ 排名和引用仍以 child 的文件名、页码为准
```

## 为什么使用 small-to-big

直接使用大块：

- 语义容易被多个主题稀释；
- 向量排名可能下降；
- 上下文包含无关内容。

只使用小块：

- 召回更精准；
- 但回答时可能缺少前后文；
- 单一列表项可能无法独立回答问题。

small-to-big 同时利用：

```text
child：提高召回和排序
parent：提供完整回答上下文
```

## 层级定义

### Parent

Parent 表示同一文件、同一页码、同一标题下的完整上下文。

数据示例：

```json
{
  "parent_id": "AI应用开发知识手册.pdf#p2",
  "source": "AI应用开发知识手册.pdf",
  "page": 2,
  "heading": "第一章 RAG 的完整流程",
  "text": "整页或标题段下的完整文本"
}
```

设计要求：

1. Parent 不跨页；
2. Parent 不跨文件；
3. 一个页面可以有多个父块，如果页面包含多个标题；
4. 当前语料通常是一页一个标题，因此一般是一页一个父块；
5. Parent 文本用于回答，不参与向量检索排名。

### Child

Child 来自 S05 的 semantic chunks。

数据示例：

```json
{
  "child_id": "AI应用开发知识手册.pdf#p2#c0",
  "parent_id": "AI应用开发知识手册.pdf#p2",
  "text": "用于向量检索的小块文本",
  "metadata": {
    "source": "AI应用开发知识手册.pdf",
    "page": 2,
    "heading": "第一章 RAG 的完整流程",
    "block_type": "paragraph",
    "block_index": 0,
    "chunk_index": 0,
    "block_indices": "0,1,2",
    "semantic_group_size": 3,
    "parent_id": "AI应用开发知识手册.pdf#p2"
  }
}
```

设计要求：

1. Child 保留原 semantic 分块文本；
2. Child 使用 BGE 向量化并写入 Chroma；
3. Child metadata 必须保存 `parent_id`；
4. Child 的 `source` 和 `page` 是检索评测依据；
5. list_item 继续独立存在；
6. 原 `block_indices` 和 `semantic_group_size` 继续保留。

## Parent 构建规则

对每个文件和每个页面：

1. 合并该页所有 semantic child 的正文；
2. 保留标题；
3. 生成稳定 `parent_id`：

```text
文件名#p页码
```

4. 当前不做跨页合并；
5. Parent 暂时保存在独立 JSON 文件中。

推荐文件：

```text
evaluation/parent_store/S06_2_parent_store.json
```

## Child 索引规则

Chroma 集合名称：

```text
parent_child_semantic
```

Child 写入字段：

```text
id       = child_id
document = child text
metadata = source/page/heading/.../parent_id
embedding = BGE(child text)
```

## 查询和展开规则

查询时：

1. 对问题生成向量；
2. 在 child 集合中检索前 `candidate_k=10`；
3. 对 child 计算标准来源排名；
4. 按 parent_id 查找父块；
5. 记录展开后的 parent 文本长度；
6. 回答阶段使用 parent 文本；
7. 引用仍使用 child 的 source 和 page。

## 去重规则

同一个 parent 的多个 child 可能同时命中。

后续可以：

1. Parent 只保留一次；
2. 记录该 parent 的最好 child rank；
3. 统计 parent 去重前后的上下文大小；
4. 避免同一页多个 child 占据全部上下文。

S06 第一阶段先实现展开，不改变 child 排名。

## 评测指标

保留原有：

- retrieval_passed；
- Hit@1；
- Hit@4；
- Recall@4；
- MRR；
- 检索延迟。

新增：

- parent_count；
- child_count；
- 去重后的 parent 数；
- 平均展开上下文字符数；
- 平均展开上下文预估 token；
- 相同 parent 在前 4 中占用的位置数。

## 硬边界

1. 不跨页构建 Parent；
2. Parent 不参与向量召回；
3. Child 的 source/page 决定引用；
4. 展开不能改变检索通过判定；
5. 注入测试段仍作为普通不可信文本处理；
6. Parent 文本必须去重，不能重复拼接相同 child。

## 当前结论

Parent-child 的价值不是直接提高检索命中，而是：

```text
保持 child 的精确排名
+ 给回答阶段补充完整上下文
+ 控制上下文大小和重复内容
```

S06-2 将实现 parent 构建和 child 索引。
