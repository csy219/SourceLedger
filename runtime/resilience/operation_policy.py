# 这是 **B08 阶段的生产级弹性执行框架**，属于系统的横切韧性层，专门用来包裹所有大模型调用这类不稳定操作，
# 统一提供**超时控制 → 自动重试 → 熔断保护 → 优雅降级**四层容错能力。
# 它把底层的超时、重试、熔断、降级组件和模型错误分类体系结合，封装成统一的调用入口，上层业务模块不用自己写容错逻辑，就能获得生产级的可用性保障。

## 一、整体定位与架构

### 核心目标

# 解决大模型调用的常见故障：超时、限流、5xx 服务端错误、网络波动、认证失败等，避免单点故障导致整条 RAG 链路崩溃。
# 分层架构
# 上层业务调用（重写 / 生成 / 重排）
#                 ↓
#     invoke_model_with_resilience（模型专用入口）
#                 ↓
#         execute_resilient（通用弹性执行器）
#                 ↓
#     ┌─────────┬──────────┬──────────┐
#   超时重试    熔断保护    降级执行
# （S17_2） （S17_3） （S17_3）
# - 底层复用 S17 系列的基础组件
# - 本层增加：**模型错误标准化分类**、**统一结果封装**、**模型专属配置**
# - 对上层暴露两个入口：通用版和模型专用版


"""Unified timeout, retry, fallback and breaker execution."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Generic,
    TypeVar,
)

from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)
from runtime.resilience.S17_2_executor import (
    NonRetryableOperationError,
    OperationTimeout,
    RetryExhausted,
    execute_with_policy,
)
from runtime.resilience.S17_3_circuit_breaker import (
    CircuitBreaker,
)
from runtime.resilience.S17_3_fallback import (
    FallbackAttempt,
    execute_with_fallback,
)


T = TypeVar("T")


## 二、错误分类体系
# 这是整个弹性框架的基础：**先把错误分对类，后续策略才会对**。
# 设计价值：**错误驱动策略**。不是所有错误都重试，永久错误重试只会浪费资源、放大故障；只有瞬时错误才重试，最大化可用性同时最小化副作用。


# `ModelTransientError`临时、自恢复性错误自动重试
class ModelTransientError(RuntimeError):
    """可重试的模型侧临时错误"""

# `ModelRateLimitError`限流，属于临时错误重试 + 指数退避
class ModelRateLimitError(ModelTransientError):
    """HTTP 429 限流，可重试+退避"""

# `ModelServerError`服务端故障重试
class ModelServerError(ModelTransientError):
    """HTTP 5xx 服务端错误，可重试"""

# `ModelPermanentError`请求、认证、校验失败，重试也没用不重试，直接走降级
class ModelPermanentError(RuntimeError):
    """永久错误，不可重试，直接降级/报错"""

# 1. `ExecutionEnvelope` 单次执行信封
# - 对单次执行结果的统一封装
# - 包含返回值、尝试次数、执行耗时
# - 作用：统一主操作和降级操作的返回格式，方便降级执行器统一处理
@dataclass(frozen=True)
class ExecutionEnvelope(Generic[T]):
    value:T
    attempts:int
    elapsed_ms:float

# 2. `ResilientExecution` 完整弹性执行结果
# 字段	作用
# value	最终返回值
# source	结果来源：primary 主操作成功，或降级链的名称
# attempts	主操作的尝试次数
# elapsed_ms	总耗时
# fallback_attempts	所有降级尝试的详细记录，包含每个降级的状态、错误、耗时
# 设计价值：**全量可观测**。不只是返回结果，还返回完整的执行过程数据，方便监控、排障、统计故障率、降级率。
@dataclass(frozen=True)
class ResilientExecution(Generic[T]):
    value:T
    source:str
    attempts:int
    elapsed_ms:float
    fallback_attempts:tuple[FallbackAttempt,...]


# 四、`classify_model_error` —— 错误分类器
# 这是框架的核心转换函数：把五花八门的原始异常（HTTP 状态码、SDK 报错、网络错误、文本报错）统一转换成上面定义的标准错误类型，供后续策略判断。
# 设计价值：**错误归一化**。上层策略只需要认识几种标准错误，不用处理几十种不同 SDK、不同场景的异常格式。
def classify_model_error(
    exc: BaseException,
) -> Exception:
    # 已经是标准错误直接透传
    # 已经是框架内的标准错误，不重复分类
    if isinstance(
        exc,
        (
            OperationTimeout,
            RetryExhausted,
            NonRetryableOperationError,
        ),
    ):
        return exc
    if isinstance(
        exc,
        (
            ModelTransientError,
            ModelPermanentError,
        ),
    ):
        return exc

    # 按 HTTP 状态码分类
    # - 401/403 → 认证 / 权限错误 → 永久错误
    # - 400/404/422 → 请求非法 → 永久错误
    # - 429 → 限流 → 瞬时错误
    # - 500~599 → 服务端错误 → 瞬时错误
    status_code = getattr(
        exc,
        "status_code",
        None,
    )

    text = (
        f"{type(exc).__name__}: {exc}"
    ).lower()

    if status_code in {401, 403}:
        return ModelPermanentError(
            f"authentication/permission error: {exc}"
        )

    if status_code in {400, 404, 422}:
        return ModelPermanentError(
            f"invalid request error: {exc}"
        )

    if status_code == 429:
        return ModelRateLimitError(
            f"rate limited: {exc}"
        )

    if isinstance(status_code, int) and (
        500 <= status_code <= 599
    ):
        return ModelServerError(
            f"model server error: {exc}"
        )

    # **按错误文本关键词分类**
    # 状态码不存在时，用错误文本特征匹配：
    # - 含 `rate limit`/`too many requests`/`429` → 限流
    # - 含 `timeout`/`timed out`/`temporarily unavailable` → 临时错误
    # - 含 `500`/`502`/`503`/`server error` → 服务端错误
    # - 含 `invalid api key`/`unauthorized`/`bad request`/`validation` → 永久错误
    if (
        "rate limit" in text
        or "too many requests" in text
        or "429" in text
    ):
        return ModelRateLimitError(
            f"rate limited: {exc}"
        )

    if (
        "timeout" in text
        or "timed out" in text
        or "temporarily unavailable" in text
    ):
        return ModelTransientError(
            f"temporary model error: {exc}"
        )

    if (
        "500" in text
        or "502" in text
        or "503" in text
        or "504" in text
        or "server error" in text
    ):
        return ModelServerError(
            f"model server error: {exc}"
        )

    if (
        "invalid api key" in text
        or "unauthorized" in text
        or "forbidden" in text
        or "permission" in text
        or "bad request" in text
        or "validation" in text
    ):
        return ModelPermanentError(
            f"permanent model error: {exc}"
        )
    # 兜底：未知错误归为永久错误
    return ModelPermanentError(
        f"unknown model error: {exc}"
    )

# 五、`_model_call` —— 模型调用包装器
# - 作用：包裹原始的模型调用函数，捕获所有异常，调用分类器转换成标准错误后再抛出
# - 价值：在调用源头就把错误标准化，后面的重试、熔断、降级逻辑只需要处理标准错误类型。
def _model_call(func:Callable[[],T])->T:
    try:
        return func()
    except Exception as exc:
        raise classify_model_error(exc) from exc



# 六、核心执行函数
### 1. `execute_resilient` —— 通用弹性执行入口
# 这是通用版的弹性执行器，支持任意业务操作，完整组合「超时 + 重试 + 熔断 + 降级」四层能力。
def execute_resilient(
    operation_name:str,
    primary:Callable[[],T],
    timeout_policy:TimeoutPolicy,
    retry_policy:RetryPolicy,
    fallback_chain:tuple[str,...]=(),
    fallback_handlers:dict[str,Callable[[],T]] | None = None,
    retryable_exceptions:tuple[type[BaseException],...]=(OperationTimeout,TimeoutError,ConnectionError,ModelTransientError,),
    breaker:CircuitBreaker | None =None,
)->ResilientExecution[T]:
    handlers=fallback_handlers or {}

    # ① 主操作封装：熔断 + 超时重试
    # - 有熔断器就把调用包裹进熔断器，熔断打开时直接快速失败
    # - 调用 `execute_with_policy` 执行超时 + 重试逻辑
    # - 结果封装成标准 `ExecutionEnvelope`
    def primary_call()->ExecutionEnvelope[T]:
        # 1. 先定义一个最原始的执行函数：直接调用业务逻辑
        def invoke()->T:
            return primary()
        # 2. 如果配置了熔断器，就把 invoke 替换成「被熔断器包裹的版本」
        if breaker is not None:
            invoke=lambda:breaker.call(invoke)

        # 3. 后面把 invoke 传给 execute_with_policy 执行...
        result=execute_with_policy(
            operation_name=operation_name,
            timeout_policy=timeout_policy,
            retry_policy=retry_policy,
            func=invoke,
            retryable_exceptions=retryable_exceptions,
        )
        return ExecutionEnvelope(
            value=result.value,
            attempts=result.attempts,
            elapsed_ms=result.elapsed_ms,
        )
    # ② 降级处理器封装
    # - 把每个降级函数也包装成统一的 `ExecutionEnvelope` 格式
    # - 每个降级操作单独计时、统一结构
    # - 保证降级执行器可以用统一方式调用所有处理器
    envelope_handlers:dict[str,Callable[[],ExecutionEnvelope[T]]]={}
    for name,handler in handlers.items():
        def make_handler(current:Callable[[],T])->Callable[[],ExecutionEnvelope[T]]:
            def wrapped()->ExecutionEnvelope[T]:
                started=time.perf_counter()
                value=current()
                elapsed_ms=(time.perf_counter()-started)*1000
                return ExecutionEnvelope(
                    value=value,
                    attempts=1,
                    elapsed_ms=elapsed_ms,
                )
            return wrapped
        envelope_handlers[name]=make_handler(handler)

    # ③ 执行降级链
    # - 调用降级执行器，按顺序尝试主操作 → 一级降级 → 二级降级...
    # - 直到有一个成功，或全部失败
    fallback_results=execute_with_fallback(
        primary_name=operation_name,
        primary=primary_call,
        fallback_chain=fallback_chain,
        handlers=envelope_handlers,
    )
    # ④ 组装最终结果
    # - 把降级执行的结果，组装成最终的 `ResilientExecution` 返回
    # - 完整保留来源、尝试次数、总耗时、所有降级尝试记录
    envelope=fallback_results.value
    return ResilientExecution(
        value=envelope.value,
        source=fallback_results.source,
        attempts=envelope.attempts,
        elapsed_ms=round(fallback_results.elapsed_ms,2),
        fallback_attempts=fallback_results.attempts,
    )

# 2. `invoke_model_with_resilience` —— 模型专用入口
# 这是给所有模型调用（重写、生成、重排）准备的**便捷封装**，在通用版基础上做了三个模型专属优化：

# 1. **自动错误标准化**：主操作用 `_model_call` 包裹，自动把原始异常转换成标准模型错误
# 2. **预置可重试异常**：默认配置模型场景下的可重试错误：超时、网络错误、瞬时模型错误
# 3. **简化调用**：上层不用关心重试异常列表、错误分类这些细节，直接传业务函数和策略即可

# > 
# > 设计价值：**通用能力 + 领域封装**。底层 `execute_resilient` 足够通用可以用在任何场景；上层 `invoke_model_with_resilience` 针对模型场景做专属配置，易用性和灵活性兼顾。
def invoke_model_with_resilience(
    operation_name: str,
    func: Callable[[], T],
    timeout_policy: TimeoutPolicy,
    retry_policy: RetryPolicy,
    fallback_chain: tuple[str, ...] = (),
    fallback_handlers: dict[str, Callable[[], T]] | None = None,
    breaker: CircuitBreaker | None = None,
) -> ResilientExecution[T]:
    return execute_resilient(
        operation_name=operation_name,
        primary=lambda: _model_call(func),
        timeout_policy=timeout_policy,
        retry_policy=retry_policy,
        fallback_chain=fallback_chain,
        fallback_handlers=fallback_handlers,
        retryable_exceptions=(
            OperationTimeout,
            TimeoutError,
            ConnectionError,
            ModelTransientError,
        ),
        breaker=breaker,
    )

## 七、核心设计总结

# 1. **错误驱动策略**：所有容错行为都基于错误分类，瞬时错误重试，永久错误直接降级，避免无效重试放大故障。
# 2. **四层容错体系**：超时控制 → 自动重试 → 熔断保护 → 优雅降级，逐层兜底，最大化系统可用性。
# 3. **统一结果契约**：成功失败都返回标准结构，带完整的执行过程数据，可观测、可统计、可排障。
# 4. **横切关注点**：作为基础设施层横切所有模型调用，业务逻辑里不用混杂容错代码，专注业务本身。
# 5. **向下兼容**：复用已有的 S17 基础组件，不重复造轮子，只做上层编排和领域适配。
## 在整条链路中的位置

# 它不是业务阶段，是**横切基础设施层**，包裹 B02 查询重写、B05 重排、B07 答案生成等所有涉及大模型调用的环节：
# 业务逻辑（比如生成回答）
#         ↓
# invoke_model_with_resilience 包裹
#         ↓
# 超时 → 重试 → 熔断 → 降级
#         ↓
# 标准结果返回给业务层
# 后续所有模型模块的异常处理、重试逻辑、降级策略，都可以统一收敛到这个框架来管理，不用每个模块各自写 try-except 和降级逻辑



    


