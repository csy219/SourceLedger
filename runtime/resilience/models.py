# 每一段

# TimeoutPolicy
# 一个操作最长允许执行多少毫秒

# RetryPolicy
# 最多尝试次数
# 基础退避
# 最大退避
# jitter 比例

# FallbackPolicy
# 失败后按顺序尝试哪些降级方案

# RateLimitPolicy
# 限流开关、限制次数、时间窗口、key 模板

# IdempotencyPolicy
# 幂等开关、key 模板、TTL

# OperationPolicy
# 把某个操作的全部失败策略组合起来

# ResilienceConfig
# 所有操作的策略集合

from dataclasses import dataclass

@dataclass(frozen=True)
class TimeoutPolicy:
    timeout_ms:int

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts:int
    base_delay_ms:int
    max_delay_ms:int
    jitter_ratio:float=0.0

@dataclass(frozen=True)
class FallbackPolicy:
    chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class RateLimitPolicy:
    enabled: bool
    limit: int
    window_seconds: int
    key_template: str


@dataclass(frozen=True)
class IdempotencyPolicy:
    enabled: bool
    key_template: str
    ttl_seconds: int = 86400


@dataclass(frozen=True)
class OperationPolicy:
    name: str
    timeout: TimeoutPolicy
    retry: RetryPolicy
    fallback: FallbackPolicy
    rate_limit: RateLimitPolicy
    idempotency: IdempotencyPolicy


@dataclass(frozen=True)
class ResilienceConfig:
    operations: dict[str, OperationPolicy]