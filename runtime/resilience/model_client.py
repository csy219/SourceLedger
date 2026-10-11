# 这是 **B08 阶段的生产级弹性大模型客户端**，是对前面讲的通用弹性执行框架的**业务层封装**，专门面向大模型调用场景，内置「主模型 → 缓存兜底 → 轻量模型降级」三级容错，配合超时控制、自动重试，直接给上层业务（查询重写、答案生成、重排等）使用，上层不用再自己写任何容错逻辑。
# > 关于你提到的 `https://api.deepseek.com` 网页解析失败：这是正常现象。该地址是 **API 接口端点**，返回 JSON 格式的接口响应，不是普通 HTML 网页，因此网页解析工具会报错。代码中是通过 `ChatOpenAI` 客户端以 HTTP 协议调用接口，并非解析网页，该报错不影响代码运行，配置正确 API 密钥即可正常调用。
## 一、整体定位

# - 定位：大模型调用的统一入口，封装所有韧性策略
# - 底层依赖：`invoke_model_with_resilience` 通用弹性执行器
# - 内置降级链：主模型失败 → 命中缓存则返回缓存 → 都不行则降级到更小更快的模型
# - 价值：把「超时、重试、熔断、降级、缓存」这些横切关注点全部封装在客户端内部，上层业务代码只需要正常调用 `invoke(messages)` 即可，完全感知不到容错逻辑。

"""Resilient chat model client."""


from __future__ import annotations

import os
from typing import Any, Callable

from langchain_openai import ChatOpenAI

from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)
from runtime.resilience.operation_policy import (
    ResilientExecution,
    invoke_model_with_resilience,
)


# 二、小模型工厂函数
### 作用

# 这是**降级用的轻量模型工厂**，默认构建 `deepseek-chat`（标准聊天模型，比主模型如 `deepseek-v4-flash` 更轻量、成本更低、可用性更高），作为主模型故障时的降级选项。

# ### 设计点

# - 工厂模式：不直接返回实例，而是返回构建函数，支持**懒加载**，真正需要降级的时候才创建实例，不提前占用资源。
# - 配置独立：降级模型的配置和主模型解耦，可以单独设置超时、参数。
def build_smaller_chat_model(
    timeout_seconds: float = 60.0,
) -> ChatOpenAI:
    api_key = os.getenv(
        "DEEPSEEK_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not configured"
        )

    return ChatOpenAI(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=api_key,
        temperature=0,
        max_tokens=1200,
        timeout=timeout_seconds,
    )


# 三、`ResilientChatClient` 弹性客户端核心类
# 参数 / 成员	作用	默认值
# primary_llm	主模型实例，主力使用的大模型，比如 deepseek-v4	必填
# fallback_llm	预注入的备用模型，可直接传入	空
# fallback_llm_factory	备用模型工厂函数，懒加载时调用	build_smaller_chat_model
# timeout_policy	超时策略	默认 6000ms（6 秒）
# retry_policy	重试策略	默认 3 次重试，基础延迟 500ms，最大 800ms，加 20% 随机抖动
# operation_name	操作名称，用于监控、追踪、熔断统计	"model.invoke"
# last_execution	保存上一次执行的完整弹性结果，包含来源、尝试次数、降级记录等，用于排查问题	None
# _response_cache	内存缓存字典，按 cache_key 存储历史成功响应，用于缓存降级	空字典
class ResilientChatClient:
    def __init__(
        self,
        primary_llm: Any,
        fallback_llm: Any | None = None,
        fallback_llm_factory: (
            Callable[[], Any] | None
        ) = None,
        timeout_policy: (
            TimeoutPolicy | None
        ) = None,
        retry_policy: (
            RetryPolicy | None
        ) = None,
        operation_name: str = "model.invoke",
    ) -> None:
        self.primary_llm = primary_llm
        self.fallback_llm = fallback_llm
        self.fallback_llm_factory = (
            fallback_llm_factory
            or build_smaller_chat_model
        )
        self.timeout_policy = (
            timeout_policy
            or TimeoutPolicy(
                timeout_ms=60000
            )
        )
        self.retry_policy = (
            retry_policy
            or RetryPolicy(
                max_attempts=3,
                base_delay_ms=500,
                max_delay_ms=8000,
                jitter_ratio=0.2,
            )
        )
        self.operation_name = (
            operation_name
        )
        self.last_execution: (
            ResilientExecution[Any]
            | None
        ) = None
        self._response_cache: dict[
            str,
            Any,
        ] = {}

    # 2. `_get_fallback_llm` —— 懒加载降级模型
    # - 作用：第一次需要降级的时候才创建备用模型实例，之后复用。
    # - 设计价值：**懒加载**。如果主模型一直稳定，就永远不会创建降级模型，节省内存和初始化开销。
    def _get_fallback_llm(
        self,
    ) -> Any:
        if self.fallback_llm is None:
            self.fallback_llm = (
                self.fallback_llm_factory()
            )

        return self.fallback_llm

    ### 3. `invoke` —— 核心调用方法
    # 这是对外的唯一主入口，输入消息列表和缓存键，返回模型响应，内部自动完成所有容错逻辑。
    def invoke(
        self,
        messages: list[Any],
        cache_key: str,
    ) -> Any:
        def primary() -> Any:
            return self.primary_llm.invoke(
                messages
            )

        def cached_response() -> Any:
            if (
                cache_key
                not in self._response_cache
            ):
                raise RuntimeError(
                    "no cached model response"
                )

            return self._response_cache[
                cache_key
            ]

        def smaller_model() -> Any:
            return (
                self._get_fallback_llm()
                .invoke(messages)
            )

        result = (
            invoke_model_with_resilience(
                operation_name=(
                    self.operation_name
                ),
                func=primary,
                timeout_policy=(
                    self.timeout_policy
                ),
                retry_policy=(
                    self.retry_policy
                ),
                fallback_chain=(
                    "cached_response",
                    "smaller_model",
                ),
                fallback_handlers={
                    "cached_response": (
                        cached_response
                    ),
                    "smaller_model": (
                        smaller_model
                    ),
                },
            )
        )

        # 1. **保存执行记录**：把完整的弹性执行结果存到 `last_execution`，方便外部排查问题、查看降级情况。
        # 2. **缓存更新策略**：**只有主模型成功的时候，才更新缓存**。
        # - 目的：保证缓存里存的都是高质量的主模型结果
        # - 降级得到的结果（缓存命中、小模型）不回写缓存，避免缓存质量下降
        # 3. **返回最终值**：只返回业务结果，上层感知不到内部的容错过程。
        self.last_execution = result

        if (
            result.source
            == self.operation_name
        ):
            self._response_cache[
                cache_key
            ] = result.value

        return result.value

# 调用 invoke(messages, cache_key)
#     ↓
# invoke_model_with_resilience 启动
#     ↓
# ┌─ 尝试主模型调用
# │   ├─ 超时控制
# │   ├─ 失败自动重试（最多3次）
# │   └─ 成功 → 更新缓存 → 返回结果
#     ↓ 主模型重试耗尽仍失败
# ├─ 一级降级：查缓存
# │   └─ 命中 → 返回缓存结果
# │   └─ 未命中 → 失败，继续降级
#     ↓ 缓存失败
# └─ 二级降级：调用轻量小模型
#     └─ 成功 → 返回小模型结果
#     └─ 失败 → 最终失败
#     ↓
# 返回最终结果，保存执行记录

## 五、核心设计亮点

# 1. **三级容错，逐级兜底**：主模型 → 缓存 → 小模型，从质量优先到可用性优先，兼顾效果和稳定性。
# 2. **缓存只存主模型结果**：降级结果不污染缓存，保证缓存的质量底线。
# 3. **全懒加载**：降级模型、缓存都按需创建，正常运行时无额外开销。
# 4. **可观测性内置**：`last_execution` 保留完整执行细节，成功失败、重试次数、降级路径都可查。
# 5. **业务无侵入**：上层业务只需要正常传消息调用，完全不用管容错逻辑，代码干净。
