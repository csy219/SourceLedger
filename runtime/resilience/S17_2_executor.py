# 这段代码是 **S17-2「timeout + retry + backoff 执行器」的完整核心实现**，
# 是整个弹性容错层最基础的执行原语。它接收上一节加载的超时、重试策略，包裹真实的业务函数，
# 自动完成「超时打断 → 失败判断 → 指数退避 → 抖动等待 → 重试执行 → 耗尽抛出」的全流程，同时定义了标准化的异常体系和结果结构，供上层熔断、降级、幂等组件调用。

import time
import random
from concurrent.futures import (
    # 单工作线程池
    # 同步代码无法主动中断自身执行，因此把业务函数放到子线程中运行，主线程来控制超时时间，
    # 是同步场景下实现超时打断的标准方案。
    ThreadPoolExecutor,

    # 线程池原生超时异常
    # 子线程执行超时时抛出的原生异常，代码里会捕获它并包装成自定义的 `OperationTimeout`，统一异常语义。
    TimeoutError as FutureTimeoutError,
)
# 快速定义数据类
# 用来定义 `ExecutionResult` 结果对象，自动生成构造函数、等值判断等，不用手写大量样板代码。
from dataclasses import dataclass

from typing import (
    Any,
    # 标记可调用对象类型
    # 用来标注被包裹的业务函数 `func` 的类型，保证传入的是可执行函数。
    Callable,
    # 泛型编程支持
    # 让执行器可以保留原始业务函数的返回值类型，实现类型安全的包裹 —— 输入什么类型的函数，
    # 返回结果里的 value 就是什么类型，IDE 可以正常补全和类型检查。
    Generic,
    TypeVar,
)

from runtime.S15_failure_policy_reference import(
    calculate_backoff_ms,
)
from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)

T=TypeVar("T")

# 单次调用执行超过超时时间
# 属于可重试故障，继续重试
class OperationTimeout(TimeoutError):
    def __init__(
            self,
            operation_name:str,
            timeout_ms:int,
    )->None:
        super().__init__(
            f"{operation_name} 超时:"
            f"{timeout_ms}ms"
        )
        self.operation_name=operation_name
        self.timeout_ms=timeout_ms

# `r`遇到不在白名单内的异常（比如参数错误、权限错误）
# 不可重试，直接终止，返回失败
class NonRetryableOperationError(RuntimeError):
    def __init__(
        self,
        operation_name: str,
        attempts: int,
        last_error: BaseException,
    ) -> None:
        super().__init__(
            f"{operation_name} 不可重试错误: "
            f"attempts={attempts}, "
            f"last_error={last_error}"
        )
        self.operation_name = operation_name
        self.attempts = attempts
        self.last_error = last_error


# 所有重试次数全部用完依然失败
# 重试耗尽，触发 fallback 降级兜底
class RetryExhausted(RuntimeError):
    def __init__(
        self,
        operation_name: str,
        attempts: int,
        last_error: BaseException,
    ) -> None:
        super().__init__(
            f"{operation_name} 重试耗尽: "
            f"attempts={attempts}, "
            f"last_error={last_error}"
        )
        self.operation_name = operation_name
        self.attempts = attempts
        self.last_error = last_error

@dataclass(frozen=True)
class ExecutionResult(Generic[T]):
    value: T
    attempts: int
    elapsed_ms: float


# 1. `run_with_timeout`：基于线程池的同步超时控制
#### 实现逻辑与设计原因

# - **为什么用线程池**：Python 的同步代码无法在主线程中主动打断执行，只能把业务函数放到子线程运行，主线程等待并控制超时。这是同步场景下做超时控制的标准方案。
# - **超时处理**：到达超时时间后，主动取消 future，并抛出自定义的 `OperationTimeout`，而不是原生的 `FutureTimeoutError`，统一异常语义。
# - **资源清理**：`finally` 中强制关闭线程池、取消待执行任务，确保无论成功失败还是超时，都不会泄漏线程。
def run_with_timeout(operation_name:str,timeout_ms:int,func:Callable[[],T])->T:
    executor=ThreadPoolExecutor(max_workers=1)
    try:
        future=executor.submit(func)
        try:
            return future.result(timeout=timeout_ms/1000.0)
        except FutureTimeoutError as exc:
            future.cancel()
            raise OperationTimeout(
                operation_name=operation_name,
                timeout_ms=timeout_ms,
            ) from exc
    finally:
        executor.shutdown(wait=False,cancel_futures=True)

# 2. `apply_jitter`：退避时间加随机抖动
# - **作用**：避免「惊群效应」。如果大量请求同时失败、同时按固定间隔重试，会在同一时刻冲击下游服务，可能直接把下游打垮。
# - **逻辑**：在计算出的基础退避时间的 ± 抖动比例范围内取随机值，把重试时间分散开，平滑下游流量。
def apply_jitter(delay_ms:float,jitter_ratio:float)->float:
    lower=delay_ms * (1.0-jitter_ratio)
    upper=delay_ms * (1.0+jitter_ratio)
    return max(0.0,random.uniform(lower,upper))

# 3. `is_retryable`：可重试异常白名单判断
# - **设计思想**：不是所有错误都值得重试。比如参数错误、权限错误、业务校验错误，重试多少次都不会成功，反而浪费资源。
# - **默认白名单**：超时、连接错误这类**临时性、可恢复的故障**才会重试，符合生产环境最佳实践。
def is_retryable(error:BaseException,retryable_exceptions:tuple)->bool:
    return isinstance(error,retryable_exceptions)


## 三、主执行逻辑：`execute_with_policy`

# 这是对外的核心入口，完整实现「超时 + 重试 + 退避 + 抖动」的全流程。
# 开始计时 → 循环尝试（共 max_attempts 次）
#     ↓
# 执行业务函数（带超时控制）
#     ↓ 成功
# 返回结果（携带值、尝试次数、总耗时）
#     ↓ 失败
# 判断是否可重试 → 不可重试 → 抛出 NonRetryableOperationError
#     ↓ 可重试
# 判断是否还有次数 → 无次数 → 跳出循环
#     ↓ 有次数
# 计算指数退避时间 → 叠加随机抖动 → sleep 等待 → 下一次循环
#     ↓ 循环结束
# 抛出 RetryExhausted（携带最后一次异常）
def execute_with_policy(
        operation_name:str,
        timeout_policy:TimeoutPolicy,
        retry_policy:RetryPolicy,
        func:Callable[[],T],
        retryable_exceptions:tuple[type[BaseException],...,]=
        (
            OperationTimeout,
            TimeoutError,
            ConnectionError,
        ),
)->ExecutionResult[T]:
    started=time.perf_counter()
    last_error:BaseException | None=None

    for attempt in range(1,retry_policy.max_attempts + 1):
        try:
            value=run_with_timeout(
                operation_name=operation_name,
                timeout_ms=timeout_policy.timeout_ms,
                func=func,
            )
            elapsed_ms=(time.perf_counter()-started)*1000
            return ExecutionResult(
                value=value,
                attempts=attempt,
                elapsed_ms=round(elapsed_ms,2)
            )
        except BaseException as exc:
            last_error=exc

            if not is_retryable(exc,retryable_exceptions):
                raise NonRetryableOperationError(
                    operation_name=operation_name,
                    attempts=attempt,
                    last_error=exc,
                ) from exc
            if attempt>=(retry_policy.max_attempts):
                break
            delay_ms=calculate_backoff_ms(
                attempt=attempt,
                base_delay_ms=retry_policy.base_delay_ms,
                max_delay_ms=retry_policy.max_delay_ms,
            )
            delay_ms=apply_jitter(float(delay_ms),retry_policy.jitter_ratio)
            time.sleep(delay_ms / 1000.0)
    if last_error is None:
        raise RuntimeError(
            "执行失败但没有记录异常"
        )
    raise RetryExhausted(
        operation_name=operation_name,
        attempts=retry_policy.max_attempts,
        last_error=last_error,
    ) from last_error

# ### 关键细节

# 1. **尝试次数从 1 开始计数**：符合人的认知，第一次执行就是第 1 次尝试，和配置里的 `max_attempts` 语义对齐。
# 2. **高精度计时**：使用 `time.perf_counter()` 统计耗时，比 `time.time()` 精度更高，适合性能监控与埋点。
# 3. **结果封装**：成功时返回 `ExecutionResult[T]`，除了业务返回值，还附带尝试次数和总耗时，方便上层做统计、日志、限流决策。
# 4. **不可变结果**：`ExecutionResult` 使用 `frozen=True`，对象创建后不可修改，避免后续逻辑意外篡改执行结果。

# ---

# ## 四、关键设计亮点

# ### 1. 策略与执行完全解耦

# 执行器不硬编码任何超时、重试参数，全部通过 `TimeoutPolicy`、`RetryPolicy` 配置对象传入。不同操作可以传入不同策略，改配置不用改执行逻辑。

# ### 2. 泛型类型保留

# 通过 `TypeVar` + `Generic[T]` 实现泛型，包裹后的函数可以保留原始返回值的类型信息，IDE 代码补全和类型检查都能正常工作。

# ### 3. 失败语义清晰

# 三种异常对应三种失败状态，上层熔断、降级组件可以精准捕获处理：

# - 捕获 `OperationTimeout`：统计超时率
# - 捕获 `NonRetryableOperationError`：直接计入失败，不重试
# - 捕获 `RetryExhausted`：触发 fallback 兜底链

# ### 4. 边界处理完备

# - 抖动后延迟不为负
# - 重试次数边界校验
# - 异常链完整保留
# - 线程资源强制清理

# ---

# ## 五、和现有体系的衔接与典型用法

# ### 1. 上下游衔接

# - **上游**：输入就是上一节 `load_resilience_config` 解析出的策略对象，配置和执行一一对应。
# - **下游**：包裹真实的业务逻辑（比如 shell 调用、HTTP 请求、数据库操作）。
# - **上层**：熔断、fallback、幂等、限流组件都会基于这个执行器封装，捕获对应异常做后续处理。
# - **仓储联动**：上层工具执行器会在执行前后调用 `ToolCallRepository`，自动更新工具调用的状态、重试次数、错误信息。

# ### 2. 典型使用示例

# ```
# # 从配置中取出对应操作的策略
# policy = resilience_config.operations["shell.run"]

# # 用执行器包裹真实业务函数
# result = execute_with_policy(
#     operation_name="shell.run",
#     timeout_policy=policy.timeout,
#     retry_policy=policy.retry,
#     func=lambda: execute_shell("pytest -q"),
#     retryable_exceptions=(OperationTimeout, ConnectionError),
# )

# print(f"结果: {result.value}")
# print(f"尝试次数: {result.attempts}")
# print(f"总耗时: {result.elapsed_ms}ms")
# ```

# ---

# 补充说明：这是**同步版本**的执行器，适合同步的工具调用场景；如果是异步架构（基于 asyncio），通常会用 `asyncio.wait_for()` 实现超时，不需要线程池，性能和资源占用会更优。