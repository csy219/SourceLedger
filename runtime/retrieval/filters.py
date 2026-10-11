# 这是 **B03 阶段的共享过滤适配层**，上游承接 B01 定义的 `RetrievalFilters` 标准契约，
# 下游对接不同的检索引擎（Chroma 向量库、BM25 内存检索），把统一的过滤条件转换成各引擎能识别的格式。核心价值是**全链路过滤规则统一**，避免向量检索和 BM25 检索各自写过滤逻辑导致标准不一致。
# - 文件定位：检索层的公共工具函数，供向量检索、BM25 检索、后处理校验等多个场景复用
# - 输入：统一的 `RetrievalFilters` 契约对象
# - 输出两种形态：
#   1. `matches_filters`：布尔匹配函数，用于内存中逐条校验文档
#   2. `build_chroma_where`：Chroma 原生查询条件，用于数据库层面下推过滤

from __future__ import annotations
from typing import Any
from runtime.rag_contracts import RetrievalFilters

# 一、`matches_filters` —— 内存级逐条过滤
# \参数	用途
# source	待检查文档的来源名称
# page	待检查文档的页码
# metadata	待检查文档的元数据字典
# filters	标准过滤条件契约
# 返回值	符合所有条件返回 True，任意一条不满足返回 False

### 典型使用场景

# - BM25 检索（纯内存检索，不支持数据库下推过滤），检索出候选后用这个函数做二次过滤
# - 检索后处理阶段，对融合后的候选做二次校验
# - 单元测试里校验过滤结果是否正确
def matches_filters(
    source:str,
    page:int,
    metadata:dict[str,Any],
    filters:RetrievalFilters,
)->bool:
    # 数据源过滤
    # - 逻辑：如果过滤器指定了数据源列表，且当前文档不在列表内，直接不通过
    # - 注意：`filters.sources` 为空元组时，条件不触发，相当于不过滤
    if filters.sources and source not in filters.sources:
        return False
    # 页码过滤
    if filters.pages and page not in filters.pages:
        return False
    # 文档 ID 过滤
    # - 逻辑：指定了文档 ID 列表时，从元数据里取出 `document_id` 字段，统一转成字符串后比对
    # - 细节：转字符串是为了规避类型不一致问题（比如存的时候是数字，契约里是字符串）
    if filters.document_ids :
        document_id=str(
            metadata.get("document_id","")
        )
        if document_id not in filters.document_ids:
            return False
    # 元数据精确匹配过滤
    for key,expected in filters.metadata_equals.items():
        if metadata.get(key) != expected:
            return False
    
    return True

# 二、`build_chroma_where` —— Chroma 数据库下推过滤
# Chroma 的过滤语法是类 MongoDB 的运算符风格，
# 支持 `$in`（包含于）、`$eq`（等于）、`$and`（且）等运算符，不能直接用我们的契约结构，需要做一层转换。
# 这个函数就是做这个适配，把契约转换成 Chroma 原生查询，让过滤在数据库层面执行，比内存过滤效率高很多。
def build_chroma_where(
    filters:RetrievalFilters,
)->dict[str,Any] | None:
    conditions :list[dict[str,Any]]=[]

    if filters.sources:
        conditions.append(
            {
                "source":{
                    "$in":list(
                        filters.sources
                    ),
                }
            }
        )

    if filters.pages:
        conditions.append(
            {
                "page":{
                    "$in":list(
                        filters.pages
                    ),
                }
            }
        )

    if filters.document_ids:
        conditions.append(
            {
                "document_id":{
                    "$in":list(
                        filters.document_ids
                    ),
                }
            }
        )
    for key,value in filters.metadata_equals.items():
        conditions.append(
            {
                key:{
                    "$eq":value
                },
            }
        )

    if not conditions:
        return None
    if len(conditions)==1:
        return conditions[0]

    return {
        "$and":conditions,
    }

