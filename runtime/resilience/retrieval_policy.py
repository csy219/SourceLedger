# 这是 **B08 阶段检索层的弹性封装组件**，专门给向量检索、BM25 检索这类检索操作套上生产级容错能力，复用同一套底层弹性执行框架，提供「超时控制 → 自动重试 → 缓存兜底」三级保障，同时内置 LRU 热点查询缓存，既提升稳定性，又加速高频查询。

# ## 一、整体定位

# - 包裹对象：`VectorRetriever` / `BM25Retriever` 等原始检索器
# - 底层复用：`execute_resilient` 通用弹性执行器（和模型客户端是同一套底层能力）
# - 核心能力：超时控制、自动重试、缓存降级、LRU 热点缓存
# - 设计目标：检索引擎（Chroma、BM25）的临时抖动、超时、故障，都被内部消化，不传导到上层 RAG 主链路；同时缓存热点查询，降低重复检索的开销。


"""Timeout, retry and cached fallback for retrievers."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from runtime.rag_contracts import (
    RetrievalCandidate,
    RetrievalFilters,
)
from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)
from runtime.resilience.operation_policy import (
    execute_resilient,
)
from runtime.resilience.S17_3_fallback import (
    FallbackAttempt,
    FallbackExhausted,
)

# 二、`RetrievalExecution` 检索执行结果
@dataclass(frozen=True)
class RetrievalExecution:
    candidates: tuple[
        RetrievalCandidate,
        ...,
    ]
    latency_ms: float
    source: str
    attempts: int
    fallback_attempts: tuple[
        FallbackAttempt,
        ...,
    ] = ()
    error: str = ""

# 三、`ResilientRetriever` 弹性检索器类
# 参数 / 成员	作用
# retriever	被包裹的原始检索器实例，比如 VectorRetriever / BM25Retriever
# operation_name	操作名称，用于监控、区分向量检索和 BM25 检索
# timeout_policy	超时策略，设置检索超时时间
# retry_policy	重试策略，设置检索失败的重试次数、退避配置
# cache_size	LRU 缓存最大条目数，默认 32，存储热点查询的结果
# self._cache	用 OrderedDict 实现的 LRU 缓存，键是缓存键，值是候选元组
# LRU 是什么、干什么用

# **LRU = Least Recently Used，最近最少使用**，是一种**缓存淘汰算法**。
# > 核心思想：**如果一个数据很久没被访问，未来大概率也不会再访问；缓存满了的时候，就把它删掉，腾出空间给新数据。**
## 放到你这段检索器代码里看
# cache_size：LRU缓存最大条目数，默认32
# self._cache：OrderedDict实现LRU缓存，key=缓存键，value=检索候选结果
# 为什么用 `OrderedDict`：可以通过 `move_to_end` 和 `popitem(last=False)` 方便地实现**LRU（最近最少使用）淘汰策略**，不需要额外引入第三方依赖。
class ResilientRetriever:
    def __init__(
        self,
        retriever: Any,
        operation_name: str,
        timeout_policy: TimeoutPolicy,
        retry_policy: RetryPolicy,
        cache_size: int = 32,
    ) -> None:
        self.retriever = retriever
        self.operation_name = (
            operation_name
        )
        self.timeout_policy = (
            timeout_policy
        )
        self.retry_policy = (
            retry_policy
        )
        self.cache_size = max(
            1,
            cache_size,
        )
        self._cache: OrderedDict[
            str,
            tuple[RetrievalCandidate, ...],
        ] = OrderedDict()

    # 2. 缓存核心方法
    # ① `_cache_key` —— 生成缓存键
    # - 作用：把「查询文本 + 过滤条件 + 返回数量」序列化成唯一字符串，作为缓存的键。
    # - 关键点：`sort_keys=True` 保证字典键顺序一致，避免相同条件因为字段顺序不同生成不同的键，导致缓存失效。
    # - 设计原则：只有查询、过滤器、top_k 完全一致，才会命中缓存，保证检索结果的准确性。
    def _cache_key(self,query:str,filters:RetrievalFilters,top_k:int)->str:
        return json.dumps(
            {"query":query,"filters":filters.to_dict(),"top_k":top_k},
            ensure_ascii=False,
            sort_keys=True,
        )

    # ② `_get_cached` —— 读取缓存
    # - 命中：把该键移到字典末尾（标记为「最近使用」），然后返回结果。
    # - 未命中：抛出异常，触发降级失败，继续后续逻辑。
    # - LRU 原理：每次访问都移到末尾，越靠后的元素越新，越靠前的越久没被访问
    def _get_cached(self,key:str)->tuple[RetrievalCandidate,...]:
        if key not in self._cache:
            raise RuntimeError("no cached retrieval result")
        self._cache.move_to_end(key)
        return self._cache[key]

    # ③ `_put_cache` —— 写入缓存
    # - 写入缓存，移到末尾（标记为最新）。
    # - 超过缓存大小时，`popitem(last=False)` 弹出**最前面**的元素，也就是最久没使用的，实现 LRU 淘汰。
    # - 效果：缓存永远只保留最近最常用的热点查询，内存占用可控。
    def _put_cache(self,key:str,candidates:tuple[RetrievalCandidate,...])->None:
        self._cache[key]=candidates
        self._cache.move_to_end(key)
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    # 3. `search` —— 核心检索方法
    def search(self,query,filters:RetrievalFilters,top_k:int)->RetrievalExecution:
        # ① 初始化 + 生成缓存键
        started=time.perf_counter()
        cache_key=self._cache_key(query,filters,top_k)

        # ② 定义主操作和降级操作
        # - `primary`：主操作，调用原始检索器的 search 方法，只取候选列表，忽略原始耗时（弹性层自己统一计时）。
        # - `cached_retrieval`：降级操作，查 LRU 缓存，没有就抛异常。
        def primary() -> tuple[RetrievalCandidate, ...]:
            candidates, _ = self.retriever.search(query=query, filters=filters, top_k=top_k)
            return tuple(candidates)

        def cached_retrieval() -> tuple[RetrievalCandidate, ...]:
            return self._get_cached(cache_key)

        # ③ 执行弹性逻辑
        # 调用通用弹性执行器，执行完整容错流程：

        # 1. 调用主检索操作，内置超时控制
        # 2. 失败则按重试策略自动重试
        # 3. 重试耗尽，走降级链：尝试返回缓存结果
        # 4. 都失败则抛出 `FallbackExhausted`
        try:
            execution = execute_resilient(
                operation_name=self.operation_name,
                primary=primary,
                timeout_policy=self.timeout_policy,
                retry_policy=self.retry_policy,
                fallback_chain=("cached_retrieval",),
                fallback_handlers={"cached_retrieval": cached_retrieval},
            )
            # ④ 成功处理 + 缓存更新
            candidates=tuple(execution.value)

            # - 取出执行结果
            # - **缓存更新策略**：**只有主检索成功的时候，才写入缓存**。缓存命中的结果不回写，避免缓存数据陈旧、质量下降。
            # - 组装标准 `RetrievalExecution` 返回，带上总耗时、结果来源、尝试次数、降级记录
            if execution.source == self.operation_name:
                self._put_cache(cache_key, candidates)
            
            return RetrievalExecution(
                candidates=candidates,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                source=execution.source,
                attempts=execution.attempts,
                fallback_attempts=execution.fallback_attempts,
            )

        #         两种异常场景：

        # 1. **降级耗尽**：主操作重试完、缓存也没命中，返回失败结果，记录最大尝试次数和所有降级尝试。
        # 2. **其他异常**：比如参数错误、未预期异常，返回失败结果，记录错误信息。

        # > 
        # > 核心设计：**不向外抛出任何异常**。上层调用永远拿到一个标准的 `RetrievalExecution` 对象，通过 `source` 和 `error` 字段判断状态，不用写 try-except，主链路更稳定。
        except FallbackExhausted as exc:
            return RetrievalExecution(
                candidates=(),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                source="failed",
                attempts=self.retry_policy.max_attempts,
                fallback_attempts=exc.attempts,
                error=str(exc),
            )
        except Exception as exc:
            return RetrievalExecution(
                candidates=(),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                source="failed",
                attempts=1,
                error=f"{type(exc).__name__}: {exc}",
            )


# ## 四、核心设计亮点

# 1. **架构统一**：复用同一套 `execute_resilient` 底层弹性框架，模型调用和检索调用的容错体系一致，运维、监控、排障成本低。
# 2. **检索专属适配**：缓存键精确包含查询、过滤器、top_k，保证缓存准确性；输出结构适配检索候选格式，上层无缝替换原始检索器。
# 3. **LRU 热点缓存**：固定大小的最近最少使用缓存，加速高频重复查询，同时内存占用可控。
# 4. **三级容错**：超时控制 → 自动重试 → 缓存兜底，检索引擎临时故障时尽可能返回结果，不中断主链路。
# 5. **异常内聚**：所有错误都内部封装成标准结果，上层无感知，业务逻辑不用混杂容错代码。
# 6. **缓存质量保障**：只有主检索成功才更新缓存，降级结果不回写，避免缓存污染。

# ---

# ## 五、在整条链路中的位置

# 包裹在原始检索器外面，替换原来的直接调用：

# ```
# 原来：
# B02 → VectorRetriever.search() → 结果
# B02 → BM25Retriever.search() → 结果

# 现在：
# B02 → ResilientRetriever(VectorRetriever).search() → 弹性结果
# B02 → ResilientRetriever(BM25Retriever).search() → 弹性结果
# ```

# 给检索层也叠加上生产级的韧性和性能优化，同时完全兼容原有接口，上层代码几乎不用改造。