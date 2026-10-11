from __future__ import annotations

# 这是 **C05 弹性原语能力封装层**，属于「底层技术原语 → 标准化能力」的适配层。它把你之前学的 S17 系列底层弹性组件（超时重试、降级链、熔断器），封装成符合标准 `Capability` 契约的可调用能力，自动带上**全链路事件追踪、参数可配置、结果结构化**，既可以通过 HTTP 接口直接调用调试，也可以作为基础能力供其他业务能力复用。

# 简单说：把底层的纯技术弹性函数，包装成了**可观测、可测试、可调用**的标准化服务。
# 层级	内容	定位
# 底层	S17 原语：execute_with_policy / execute_with_fallback / CircuitBreaker	纯技术函数，只做功能，无追踪、无接口
# 本层	三个 Capability 处理器	适配层：参数解析、事件埋点、标准化输入输出
# 上层	Capability 注册中心 + FastAPI 路由	对外暴露成 HTTP 服务

### 核心目的

# 1. **可调试**：可以通过接口直接调用，传不同参数验证弹性策略效果，不用写测试代码
# 2. **可观测**：弹性执行的每一步（每次重试、每次降级、熔断状态变化）都生成标准事件，完整可追溯
# 3. **标准化**：和检索、上下文等能力格式完全统一，接入统一的框架能力
# 4. **可复用**：业务能力可以直接复用底层弹性原语，也可以通过能力框架调用


# 这一步是在之前 3 个核心弹性能力（重试退避、降级链、熔断器）的基础上，**补齐另外 4 个生产级分布式弹性能力**：
# 限流、分布式锁、请求幂等、检查点恢复。
# 它们全部基于底层 S16/S17 技术原语封装，符合标准 Capability 契约，自动带全链路事件追踪，可通过 HTTP 接口直接调用调试，共同组成完整的生产级弹性能力集。

## 一、新增基础设施辅助函数

# 因为后面 4 个能力依赖数据库和 Redis 中间件，这里先提供**线程安全的全局单例懒加载工具**，避免重复初始化、保证并发安全。
"""Thin resilience capability handlers over S17 primitives."""
import os
import threading
import uuid

from redis import Redis

from runtime.S15_state_reference import (
    RunState,
    RunStatus,
)
from runtime.db.checkpointer import (
    DatabaseCheckpointer,
)
from runtime.db.S16_3_run_repository import (
    RunStateRepository,
)
from runtime.db.S16_4_idempotency_repository import (
    IdempotencyRepository,
)
from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)
from runtime.resilience.S17_4_distributed_lock import (
    DistributedLock,
)
from runtime.resilience.S17_4_rate_limiter import (
    LocalRateLimiter,
    RedisRateLimiter,
)
from runtime.resilience.S17_5_idempotency import (
    RequestIdempotencyService,
)

import time
from typing import Any

from runtime.api.capabilities import (
    CapabilityDefinition,
    CapabilityDescriptor,
    CapabilityRegistry,
    CapabilityRunRequest,
)
from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import TraceStatus
from runtime.resilience.models import (
    RetryPolicy,
    TimeoutPolicy,
)
from runtime.resilience.S17_2_executor import (
    NonRetryableOperationError,
    RetryExhausted,
    execute_with_policy,
)
from runtime.resilience.S17_3_circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
)
from runtime.resilience.S17_3_fallback import (
    FallbackExhausted,
    execute_with_fallback,
)
from runtime.run_trace import TraceRecorder

# 第 2 步：增加数据库和 Redis 辅助函数
_SESSION_FACTORY = None
_SESSION_LOCK = threading.Lock()


def _get_session_factory():
    global _SESSION_FACTORY

    if _SESSION_FACTORY is None:
        with _SESSION_LOCK:
            if _SESSION_FACTORY is None:
                engine = create_db_engine()
                _SESSION_FACTORY = (
                    create_session_factory(engine)
                )

    return _SESSION_FACTORY


def _get_redis_client() -> Redis:
    redis_url = os.getenv(
        "REDIS_URL",
        "redis://localhost:6380/0",
    )
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
    )
    client.ping()
    return client

# 二、工具函数：`_policy_from_input`
### 作用
# **参数适配**：从 HTTP 请求的输入字典里，提取超时、重试相关参数，构造成底层原语需要的标准策略对象。
def _policy_from_input(
    payload: CapabilityRunRequest,
) -> tuple[
    TimeoutPolicy,
    RetryPolicy,
]:
    timeout_ms = int(
        payload.input.get(
            "timeout_ms",
            1000,
        )
    )
    max_attempts = int(
        payload.input.get(
            "max_attempts",
            3,
        )
    )
    base_delay_ms = int(
        payload.input.get(
            "base_delay_ms",
            10,
        )
    )
    max_delay_ms = int(
        payload.input.get(
            "max_delay_ms",
            100,
        )
    )
    jitter_ratio = float(
        payload.input.get(
            "jitter_ratio",
            0.0,
        )
    )

    return (
        TimeoutPolicy(
            timeout_ms=timeout_ms
        ),
        RetryPolicy(
            max_attempts=max_attempts,
            base_delay_ms=base_delay_ms,
            max_delay_ms=max_delay_ms,
            jitter_ratio=jitter_ratio,
        ),
    )


## 三、七个核心弹性能力处理器
# 每个都严格符合 `CapabilityHandler` 契约：`(请求, 记录器) → 结果字典`，内部完整埋点。

#### 内部执行逻辑
# 1. 从输入提取超时、重试策略
# 2. 读取 `succeed_on_attempt` 参数：控制第几次尝试才成功（模拟临时故障）
# 3. 定义模拟操作函数：
#    - 每次调用计数 +1
#    - 记录一条「重试中」事件
#    - 没到指定次数就抛 `ConnectionError`（模拟临时故障）
#    - 到指定次数返回成功
# 4. 调用 `execute_with_policy` 执行带重试策略的操作
# 5. **三种结果分支，分别埋点**：
#    - ✅ **成功**：记录成功事件，返回状态、尝试次数、耗时、结果
#    - ❌ **重试耗尽**：所有重试都用完还是失败，记录耗尽事件，返回错误
#    - 🚫 **不可重试错误**：遇到非重试类错误，直接拒绝，记录拒绝事件

# #### 设计价值
# - 可以通过接口传参，控制第几次成功，直观验证重试次数、退避延迟、超时是不是符合预期
# - 每次尝试都有事件，整条重试时间线可追溯，排障不用打日志

# 1. `retry_backoff_handler` —— 重试退避能力
# **对应底层原语**：`execute_with_policy`（超时 + 自动重试 + 指数退避）
# **定位**：验证「超时重试 + 退避」机制是否正常工作的调试能力。
def retry_backoff_handler(
        payload:CapabilityRunRequest,
        recorder:TraceRecorder,
)->dict[str,Any]:
    run_id=payload.run_id or "cap-retry-backoff"
    timeout_policy,retry_policy=_policy_from_input(payload)
    succeed_on_attempt=int(payload.input.get("succeed_on_attempt",3))
    attempts={"count":0}

    def operation()->dict[str,Any]:
        attempts["count"]+=1
        current=attempts["count"]

        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:retry:"
                    f"attempt:{current}"
                ),
                run_id=run_id,
                stage="resilience",
                operation="retry_backoff",
                status=TraceStatus.RETRYING,
                attempt=current,
                action="execute_operation",
                metadata={
                    "succeed_on_attempt": (
                        succeed_on_attempt
                    ),
                },
            )
        )
        if current < succeed_on_attempt:
            raise ConnectionError(
                f"temporary failure at "
                f"attempt {current}"
            )

        return {
            "value": "ok",
            "attempt": current,
        }
    try:
        result = execute_with_policy(
            operation_name="capability.retry",
            timeout_policy=timeout_policy,
            retry_policy=retry_policy,
            func=operation,
            retryable_exceptions=(
                TimeoutError,
                ConnectionError,
            ),
        )

        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:retry:success"
                ),
                run_id=run_id,
                stage="resilience",
                operation="retry_backoff",
                status=TraceStatus.SUCCEEDED,
                attempt=result.attempts,
                action="retry_success",
                duration_ms=result.elapsed_ms,
                metadata={
                    "attempts": result.attempts,
                },
            )
        )

        return {
            "status": "succeeded",
            "attempts": result.attempts,
            "elapsed_ms": result.elapsed_ms,
            "value": result.value,
        }

    except RetryExhausted as exc:
        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:retry:exhausted"
                ),
                run_id=run_id,
                stage="resilience",
                operation="retry_backoff",
                status=TraceStatus.FAILED,
                attempt=exc.attempts,
                action="retry_exhausted",
                metadata={
                    "error": str(exc),
                },
            )
        )

        return {
            "status": "exhausted",
            "attempts": exc.attempts,
            "error": str(exc.last_error),
        }

    except NonRetryableOperationError as exc:
        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:retry:non_retryable"
                ),
                run_id=run_id,
                stage="resilience",
                operation="retry_backoff",
                status=TraceStatus.REJECTED,
                attempt=exc.attempts,
                action="non_retryable",
                metadata={
                    "error": str(exc),
                },
            )
        )

        return {
            "status": "non_retryable",
            "attempts": exc.attempts,
            "error": str(exc.last_error),
        }

# 2. `fallback_chain_handler` —— 降级链能力
# **对应底层原语**：`execute_with_fallback`（主操作 → 按顺序降级）
# **定位**：验证「多级降级链路」执行顺序和结果的调试能力。

#### 内部执行逻辑
# 1. 读取 `fallback_success` 参数：控制哪一级降级成功
# 2. 定义三级执行链：
#    - `primary`：主操作，必败（模拟主服务故障）
#    - `bm25_only`：一级降级，参数匹配则成功，否则失败
#    - `cached_retrieval`：二级降级，参数匹配则成功，否则失败
# 3. 调用 `execute_with_fallback` 按顺序执行降级链
# 4. **两种结果分支**：
#    - ✅ **降级成功**：记录「降级使用」事件，返回成功来源、结果、每一级的尝试详情
#    - ❌ **全部降级失败**：记录「降级耗尽」事件，返回每一级的错误详情

# #### 设计价值
# - 可以模拟不同降级点成功，验证降级顺序是不是正确、降级链路有没有断
# - 完整返回每一次降级尝试的来源和错误，整条降级路径透明可查
def fallback_chain_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or "cap-fallback-chain"
    )
    fallback_success = str(
        payload.input.get(
            "fallback_success",
            "bm25_only",
        )
    )

    def primary() -> str:
        raise ConnectionError(
            "primary provider unavailable"
        )

    def bm25_only() -> str:
        if fallback_success != "bm25_only":
            raise RuntimeError(
                "bm25 fallback unavailable"
            )
        return "bm25-only-result"

    def cached_retrieval() -> str:
        if fallback_success != "cached_retrieval":
            raise RuntimeError(
                "cache unavailable"
            )
        return "cached-result"

    try:
        result = execute_with_fallback(
            primary_name="primary",
            primary=primary,
            fallback_chain=(
                "bm25_only",
                "cached_retrieval",
            ),
            handlers={
                "bm25_only": bm25_only,
                "cached_retrieval": (
                    cached_retrieval
                ),
            },
        )

        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:fallback:success"
                ),
                run_id=run_id,
                stage="resilience",
                operation="fallback_chain",
                status=(
                    TraceStatus.FALLBACK_USED
                ),
                action=result.source,
                duration_ms=result.elapsed_ms,
                metadata={
                    "attempts": [
                        {
                            "source": item.source,
                            "error": item.error,
                        }
                        for item in result.attempts
                    ],
                },
            )
        )

        return {
            "status": "succeeded",
            "source": result.source,
            "value": result.value,
            "elapsed_ms": result.elapsed_ms,
            "attempts": [
                {
                    "source": item.source,
                    "error": item.error,
                }
                for item in result.attempts
            ],
        }

    except FallbackExhausted as exc:
        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:fallback:exhausted"
                ),
                run_id=run_id,
                stage="resilience",
                operation="fallback_chain",
                status=TraceStatus.FAILED,
                action="fallback_exhausted",
                metadata={
                    "attempts": [
                        {
                            "source": item.source,
                            "error": item.error,
                        }
                        for item in exc.attempts
                    ],
                },
            )
        )

        return {
            "status": "exhausted",
            "attempts": [
                {
                    "source": item.source,
                    "error": item.error,
                }
                for item in exc.attempts
            ],
        }

#### 内部执行逻辑
# 1. 读取参数：失败阈值、恢复超时时间
# 2. 创建一个熔断器实例
# 3. **第一步：触发熔断**
# 连续调用失败函数，直到达到阈值，熔断器打开
# 统计失败次数
# 4. **第二步：验证熔断拦截**
# 再调用一次，预期抛出 `CircuitOpenError`，证明熔断打开后会快速失败
# 记录打开状态和错误
# 5. **第三步：等待恢复**
# sleep 等待恢复超时时间过去
# 6. **第四步：验证恢复**
# 再调用成功函数，熔断器半开放行，成功后回到关闭状态
# 记录恢复后的状态和返回值
# 7. 记录整个熔断器验证事件，返回各阶段状态

# #### 设计价值
# - 完整跑通熔断器的状态机，验证阈值、恢复时间、半开逻辑是不是正确
# - 可以通过接口调参，测试不同阈值下的熔断行为，不用写单元测试   

### 3. `circuit_breaker_handler` —— 熔断器能力

# **对应底层原语**：`CircuitBreaker`（关闭 → 打开 → 半开 → 恢复关闭 状态机）
# **定位**：验证熔断器完整状态流转的调试能力，覆盖「失败累积 → 熔断打开 → 冷却恢复 → 半开放行 → 恢复关闭」全流程。

def circuit_breaker_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or "cap-circuit-breaker"
    )
    failure_threshold = int(
        payload.input.get(
            "failure_threshold",
            2,
        )
    )
    recovery_timeout_ms = int(
        payload.input.get(
            "recovery_timeout_ms",
            50,
        )
    )

    breaker = CircuitBreaker(
        name="capability-breaker",
        failure_threshold=(
            failure_threshold
        ),
        recovery_timeout_seconds=(
            recovery_timeout_ms / 1000
        ),
        half_open_max_calls=1,
    )

    def fail()->None:
        raise ConnectionError(
            "downstream unavailable"
        )

    failures=0
    for _ in range(failure_threshold):
        try:
            breaker.call(fail)
        except ConnectionError:
            failures+=1

    open_state=breaker.state.value
    open_error=""

    try:
        breaker.call(lambda: "blocked")
    except CircuitOpenError:
        open_error="CircuitOpenError"

    time.sleep(recovery_timeout_ms/1000)
    recovered_value=breaker.call(lambda: "recoverd")
    recovered_state=breaker.state.value

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:breaker:recovered"
            ),
            run_id=run_id,
            stage="resilience",
            operation="circuit_breaker",
            status=TraceStatus.SUCCEEDED,
            action="breaker_recovered",
            metadata={
                "failures": failures,
                "open_state": open_state,
                "open_error": open_error,
                "recovered_state": (
                    recovered_state
                ),
            },
        )
    )

    return {
        "status": "succeeded",
        "failures": failures,
        "open_state": open_state,
        "open_error": open_error,
        "recovered_value": (
            recovered_value
        ),
        "recovered_state": (
            recovered_state
        ),
    }

#### 内部执行流程
# 1. 读取参数：限流阈值、时间窗口、请求次数
# 2. 生成随机 key，避免互相干扰
# 3. **本地限流测试**：创建本地限流器，连续调用 N 次，记录每次是否允许通过
# 4. **Redis 限流测试**：创建 Redis 限流器，同样连续调用 N 次，记录每次结果
# 5. 记录限流事件，带上两种实现的结果对比
# 6. 返回结构化结果：两种实现的每次请求是否通过

# #### 设计价值
# - 同时验证本地和分布式两种限流实现的正确性
# - 可以通过接口传参，测试不同阈值、不同窗口下的限流行为
# - 两种结果对比，方便排查分布式限流的同步问题

### 4. `rate_limit_handler` —— 限流能力
# **对应底层原语**：`LocalRateLimiter`（本地令牌桶）+ `RedisRateLimiter`（分布式令牌桶）
# **定位**：验证本地和 Redis 两种限流策略的行为，对比限流效果。
def rate_limit_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or "cap-rate-limit"
    )
    limit = int(
        payload.input.get("limit", 2)
    )
    window_seconds = int(
        payload.input.get(
            "window_seconds",
            60,
        )
    )
    request_count = int(
        payload.input.get(
            "request_count",
            3,
        )
    )
    key = uuid.uuid4().hex

    local_limiter = LocalRateLimiter()
    local_results = [
        local_limiter.check(
            key=f"local:{key}",
            limit=limit,
            window_seconds=window_seconds,
        ).allowed
        for _ in range(request_count)
    ]

    client = _get_redis_client()
    redis_limiter = RedisRateLimiter(
        client
    )
    redis_results = [
        redis_limiter.check(
            key=f"redis:{key}",
            limit=limit,
            window_seconds=window_seconds,
        ).allowed
        for _ in range(request_count)
    ]

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:rate-limit"
            ),
            run_id=run_id,
            stage="resilience",
            operation="rate_limit",
            status=TraceStatus.SUCCEEDED,
            action="check_rate_limit",
            metadata={
                "limit": limit,
                "window_seconds": (
                    window_seconds
                ),
                "request_count": (
                    request_count
                ),
                "local_results": (
                    local_results
                ),
                "redis_results": (
                    redis_results
                ),
            },
        )
    )

    return {
        "status": "succeeded",
        "limit": limit,
        "window_seconds": window_seconds,
        "local_results": local_results,
        "redis_results": redis_results,
    }

#### 内部执行流程
# 1. 读取参数：锁 TTL（过期时间）
# 2. 生成唯一锁 key
# 3. 创建两个指向同一个 key 的锁实例（模拟两个进程 / 节点）
# 4. **第一步**：第一个锁加锁 → 应该成功
# 5. **第二步**：第二个锁在第一个锁持有期间加锁 → 应该失败（互斥）
# 6. **第三步**：释放第一个锁
# 7. **第四步**：第二个锁再加锁 → 应该成功（锁已释放）
# 8. 释放第二个锁
# 9. 记录锁事件，返回每一步的成功 / 失败状态

# #### 设计价值
# - 完整验证分布式锁的核心语义：**同一时间只有一个持有者**
# - 覆盖「加锁成功、持有中互斥、释放后可重入」全场景
# - 可以通过接口测试不同 TTL 下的锁过期、自动释放行为

### 2. `distributed_lock_handler` —— 分布式锁能力
# **对应底层原语**：`DistributedLock`（基于 Redis 的分布式互斥锁）
# **定位**：验证分布式锁的互斥性、加锁释放逻辑是否正确。
def distributed_lock_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or "cap-distributed-lock"
    )
    ttl_ms = int(
        payload.input.get("ttl_ms", 500)
    )
    key = (
        "capability-lock:"
        f"{uuid.uuid4().hex}"
    )

    client = _get_redis_client()
    first_lock = DistributedLock(
        client=client,
        key=key,
        ttl_ms=ttl_ms,
    )
    second_lock = DistributedLock(
        client=client,
        key=key,
        ttl_ms=ttl_ms,
    )

    first_acquired = first_lock.acquire()
    second_acquired_while_held = (
        second_lock.acquire()
    )
    first_released = first_lock.release()
    second_acquired_after_release = (
        second_lock.acquire()
    )
    second_released = second_lock.release()

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:distributed-lock"
            ),
            run_id=run_id,
            stage="resilience",
            operation="distributed_lock",
            status=TraceStatus.SUCCEEDED,
            action="lock_acquire_release",
            metadata={
                "first_acquired": (
                    first_acquired
                ),
                "second_acquired_while_held": (
                    second_acquired_while_held
                ),
                "first_released": (
                    first_released
                ),
                "second_acquired_after_release": (
                    second_acquired_after_release
                ),
                "second_released": (
                    second_released
                ),
            },
        )
    )

    return {
        "status": "succeeded",
        "first_acquired": first_acquired,
        "second_acquired_while_held": (
            second_acquired_while_held
        ),
        "first_released": first_released,
        "second_acquired_after_release": (
            second_acquired_after_release
        ),
        "second_released": second_released,
    }


#### 内部执行流程
# 1. 读取参数：幂等 key（没传就自动生成）
# 2. 获取数据库会话工厂，创建幂等服务
# 3. 定义业务函数：调用一次计数 +1，返回结果
# 4. **第一次调用**：传入相同 key，执行业务函数，返回结果
# 5. **第二次调用**：传入完全相同的 key，**业务函数不会重复执行**，直接返回第一次的结果
# 6. 记录幂等事件，返回两次调用的「是否重放」标记、业务实际调用次数、最终结果

# #### 核心验证点
# - `call_count` 最终 = 1：证明业务逻辑只执行了一次
# - 第二次 `replayed = True`：证明是直接重放历史结果
# - 两次返回的 value 完全一致

# #### 设计价值
# - 验证幂等机制的核心效果：重复请求不重复执行业务，结果一致
# - 模拟重复提交、重试等场景，验证接口的幂等性保护
# - 对应生产场景：前端重复提交、网络重试、消息重复消费等

### 3. `idempotency_handler` —— 请求幂等能力
# **对应底层原语**：`RequestIdempotencyService` + `IdempotencyRepository`（数据库幂等表）
# **定位**：验证「相同 key 的请求重复调用，只执行一次，后续直接返回历史结果」的幂等机制。
def idempotency_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or f"idem-{uuid.uuid4().hex}"
    )
    key = str(
        payload.input.get("key")
        or f"capability:{uuid.uuid4().hex}"
    )
    session_factory = (
        _get_session_factory()
    )
    service = RequestIdempotencyService(
        IdempotencyRepository(
            session_factory
        )
    )
    calls = {"count": 0}

    def business_function() -> dict[str, Any]:
        calls["count"] += 1
        return {
            "value": "idempotent-result",
            "call": calls["count"],
        }

    first = service.execute(
        key=key,
        run_id=run_id,
        func=business_function,
    )
    second = service.execute(
        key=key,
        run_id=run_id,
        func=business_function,
    )

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:idempotency"
            ),
            run_id=run_id,
            stage="resilience",
            operation="idempotency",
            status=TraceStatus.SUCCEEDED,
            action="replay_existing_result",
            metadata={
                "key": key,
                "first_replayed": (
                    first.replayed
                ),
                "second_replayed": (
                    second.replayed
                ),
                "call_count": calls["count"],
            },
        )
    )

    return {
        "status": "succeeded",
        "key": key,
        "first_replayed": first.replayed,
        "second_replayed": second.replayed,
        "call_count": calls["count"],
        "value": second.value,
    }



# #### 内部执行流程
# 1. 获取数据库会话工厂，创建运行状态仓库和检查点器
# 2. 创建一个运行状态对象，设置为运行中，当前节点为 `before_crash`
# 3. **保存第一个检查点**：把当前状态持久化到数据库
# 4. **模拟恢复**：从数据库加载最新的检查点，还原运行状态
# 5. 恢复后更新状态：节点改为 `recovered`，步数 +1
# 6. **保存第二个检查点**：持久化恢复后的新状态
# 7. 列出该 run_id 的所有检查点版本
# 8. 记录检查点事件，返回版本号、恢复后的节点、步数等信息

# #### 设计价值
# - 完整验证「保存检查点 → 崩溃 → 加载恢复 → 继续执行 → 再保存」全流程
# - 对应生产场景：长流程中断（比如大模型生成、批量处理），重启后不用从头开始，从最近检查点继续
# - 可以验证多版本管理、版本回溯能力

### 4. `checkpoint_recovery_handler` —— 检查点恢复能力
# **对应底层原语**：`DatabaseCheckpointer` + `RunStateRepository`（数据库运行状态持久化）
# **定位**：验证「流程中断后，可以从最近的检查点恢复继续执行」的断点续跑能力
def checkpoint_recovery_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or f"checkpoint-{uuid.uuid4().hex}"
    )
    session_factory = (
        _get_session_factory()
    )
    run_repository = RunStateRepository(
        session_factory
    )
    checkpointer = DatabaseCheckpointer(
        session_factory
    )

    state = RunState.create(
        thread_id="capability-checkpoint",
        goal="capability checkpoint recovery",
        max_steps=10,
    )
    state.run_id = run_id
    state.status = RunStatus.RUNNING
    state.current_node = "before_crash"
    state.increment_step()

    run_repository.create(state)

    first_checkpoint = checkpointer.save(
        state,
        node="before_crash",
    )

    recovered = checkpointer.load_latest(
        run_id
    )

    if recovered is None:
        raise RuntimeError(
            "checkpoint recovery failed"
        )

    recovered.current_node = "recovered"
    recovered.increment_step()

    second_checkpoint = checkpointer.save(
        recovered,
        node="recovered",
    )

    versions = checkpointer.list_versions(
        run_id
    )

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:checkpoint-recovery"
            ),
            run_id=run_id,
            stage="resilience",
            operation="checkpoint_recovery",
            status=TraceStatus.SUCCEEDED,
            action="restore_latest_checkpoint",
            metadata={
                "first_checkpoint": (
                    first_checkpoint.version
                ),
                "second_checkpoint": (
                    second_checkpoint.version
                ),
                "versions": versions,
                "recovered_node": (
                    recovered.current_node
                ),
            },
        )
    )

    return {
        "status": "succeeded",
        "run_id": run_id,
        "first_checkpoint": (
            first_checkpoint.version
        ),
        "second_checkpoint": (
            second_checkpoint.version
        ),
        "versions": versions,
        "recovered_node": (
            recovered.current_node
        ),
        "recovered_step_count": (
            recovered.step_count
        ),
    }







# 四、能力注册函数
# 把三个弹性能力批量注册到能力注册中心，归为 `resilience`（弹性）分类。
# 能力 ID	名称	分类	标签
# retry_backoff	Retry and Backoff	resilience	retry, backoff
# fallback_chain	Fallback Chain	resilience	fallback
# circuit_breaker	Circuit Breaker	resilience	circuit, breaker

def register_core_resilience_capabilities(
    registry: CapabilityRegistry,
) -> None:
    # - **幂等注册**：已经注册过就直接跳过，避免重复注册报错。
    # - 场景：系统多个模块都可能调用注册函数，保证重复调用也不会出问题。
    if registry.has("retry_backoff"):
        return

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="retry_backoff",
                name="Retry and Backoff",
                description=(
                    "Execute an operation with "
                    "timeout, retry and backoff."
                ),
                category="resilience",
                tags=["retry", "backoff"],
            ),
            handler=retry_backoff_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="fallback_chain",
                name="Fallback Chain",
                description=(
                    "Try primary operation and "
                    "ordered fallback handlers."
                ),
                category="resilience",
                tags=["fallback"],
            ),
            handler=fallback_chain_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="circuit_breaker",
                name="Circuit Breaker",
                description=(
                    "Open, reject, recover and "
                    "close a circuit breaker."
                ),
                category="resilience",
                tags=[
                    "circuit",
                    "breaker",
                ],
            ),
            handler=circuit_breaker_handler,
        )
    )
    
    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="rate_limit",
                name="Rate Limit",
                description=(
                    "Check local and Redis "
                    "rate limit behavior."
                ),
                category="resilience",
                tags=["rate-limit", "redis"],
            ),
            handler=rate_limit_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="distributed_lock",
                name="Distributed Lock",
                description=(
                    "Acquire, reject and release "
                    "a Redis distributed lock."
                ),
                category="resilience",
                tags=["lock", "redis"],
            ),
            handler=distributed_lock_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="idempotency",
                name="Request Idempotency",
                description=(
                    "Execute the same request key "
                    "twice and replay the result."
                ),
                category="resilience",
                tags=["idempotency", "database"],
            ),
            handler=idempotency_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id="checkpoint_recovery",
                name="Checkpoint Recovery",
                description=(
                    "Save and restore a real "
                    "database checkpoint."
                ),
                category="resilience",
                tags=[
                    "checkpoint",
                    "recovery",
                ],
            ),
            handler=checkpoint_recovery_handler,
        )
    )


## 五、核心设计总结

# 1. **技术原语产品化**
# 底层的 S17 只是代码级的函数库，这一层封装后变成了**可调用、可观测、可调试**的标准化能力，有接口、有追踪、有结构化输出。
# 2. **全链路追踪内置**
# 弹性执行的每一步（每次重试、每次降级、每次状态变化）都自动生成 `CapabilityEvent`，弹性过程不再是黑盒，整条时间线可追溯。
# 3. **调试友好**
# 所有参数都可以通过接口传入，可以快速验证不同配置下的弹性行为，比如：
#    - 重试 2 次够不够？
#    - 熔断阈值设 3 会不会太灵敏？
#    - 降级顺序对不对？
#    不用写代码，直接调接口就能验证。
# 4. **统一契约，无缝接入**
# 和检索、上下文等业务能力格式完全一致，自动接入统一的 API 网关、权限、监控、日志体系。
# 5. **分层解耦**
# 底层弹性原语只做纯功能，不关心追踪、接口、参数解析；这一层只做适配和封装，不改动底层逻辑。两层独立演进，互不影响。

# ---

# ## 在整体架构中的位置

# ```
# ┌─────────────────────────────────────────┐
# │  Capability 能力框架（统一接口、追踪）  │
# └─────────┬───────────────────┬───────────┘
#           │                   │
#     检索类能力          弹性类能力 ← 本层
#           │                   │
# ┌─────────┴──────────┐ ┌────────┴──────────┐
# │ 向量/BM25/RRF/上下文│ │ 重试/降级/熔断器  │
# │   业务技术模块     │ │  弹性技术原语    │
# └────────────────────┘ └───────────────────┘
# ```

# 这一层本质上就是给弹性技术组件套上「能力外壳」，让它们和业务能力一样，融入整个标准化能力体系。