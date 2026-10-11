# 这段代码是**弹性容错层的配置加载与校验器**，对应 S17-1「定义失败策略、超时、重试和降级配置」的核心落地实现。它的核心作用是：
# 把外部 JSON 格式的容错配置文件，转换成内存中强类型的策略对象，同时做完整的合法性校验，
# 为后续的执行器提供统一、合法的配置输入。
# 简单说：**它是整个弹性层的配置入口，负责把 “配置文件” 变成 “程序能直接用的规则对象”**。

# JSON 配置文件 → load_resilience_config → 各 parse_* 解析函数
#                                               ↓
#                                         validate_operation 合法性校验
#                                               ↓
#                                     ResilienceConfig 强类型配置对象
#                                               ↓
#                                         弹性执行器运行时使用

### 对应的数据模型

# 代码里导入的 7 个模型，都是 `dataclass` 定义的策略对象，和解析函数一一对应：
# 模型	对应解析函数	作用
# TimeoutPolicy	parse_timeout	单次操作超时规则
# RetryPolicy	parse_retry	失败重试与退避规则
# FallbackPolicy	parse_fallback	降级兜底策略链
# RateLimitPolicy	parse_rate_limit	流量控制规则
# IdempotencyPolicy	parse_idempotency	幂等控制规则
# OperationPolicy	—	单个操作的完整策略包，把上面 5 种打包
# ResilienceConfig	load_resilience_config	全局配置根，包含所有操作的策略


import json
from pathlib import Path
from typing import Any

from runtime.resilience.models import (
    FallbackPolicy,
    IdempotencyPolicy,
    OperationPolicy,
    RateLimitPolicy,
    ResilienceConfig,
    RetryPolicy,
    TimeoutPolicy,
)

def parse_timeout(
    payload: dict[str, Any],
) -> TimeoutPolicy:
    return TimeoutPolicy(
        timeout_ms=int(payload["timeout_ms"])
    )


# `jitter_ratio`：抖动比例，给等待时间加随机偏移，避免大量请求同时重试造成 “惊群效应” 打爆下游
def parse_retry(
    payload: dict[str, Any],
) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=int(payload["max_attempts"]),
        base_delay_ms=int(payload["base_delay_ms"]),
        max_delay_ms=int(payload["max_delay_ms"]),
        jitter_ratio=float(
            payload.get("jitter_ratio", 0.0)
        ),
    )

# - `chain`：兜底策略名称的有序列表
# - 执行逻辑：主逻辑失败且重试耗尽后，按顺序逐个尝试兜底方案，直到有一个成功；全部失败才最终报错
def parse_fallback(
    payload: dict[str, Any],
) -> FallbackPolicy:
    return FallbackPolicy(
        chain=tuple(
            str(item)
            for item in payload.get("chain", [])
        )
    )

# - `enabled`：开关，可单独控制每个操作是否限流
# - `limit` / `window_seconds`：时间窗口内的最大调用次数，比如 60 秒 10 次
# - `key_template`：限流 key 的模板，支持变量占位，比如 `shell:{user_id}`，实现按用户、按工具等细粒度限流
def parse_rate_limit(
    payload: dict[str, Any],
) -> RateLimitPolicy:
    return RateLimitPolicy(
        enabled=bool(payload.get("enabled", False)),
        limit=int(payload.get("limit", 1)),
        window_seconds=int(
            payload.get("window_seconds", 60)
        ),
        key_template=str(
            payload.get("key_template", "")
        ),
    )

# - `key_template`：幂等 key 的模板，比如 `idem:{run_id}:{tool_call_id}`
# - `ttl_seconds`：幂等记录的过期时间，避免永久占用存储
def parse_idempotency(
    payload: dict[str, Any],
) -> IdempotencyPolicy:
    return IdempotencyPolicy(
        enabled=bool(payload.get("enabled", False)),
        key_template=str(
            payload.get("key_template", "")
        ),
        ttl_seconds=int(
            payload.get("ttl_seconds", 86400)
        ),
    )

### 2. 主加载函数 `load_resilience_config`

# 这是对外的主入口，负责完整的配置加载流程

# **核心设计**：

# - 按「操作」粒度配置：每个工具 / 接口都可以有独立的容错规则，比如 shell 命令超时设 30s，HTTP 接口超时设 5s
# - 配置外置：容错规则写在 JSON 文件里，改参数不用改业务代码，甚至可以做热加载
# - 加载即校验：配置读进来立刻校验，启动时就发现错误，避免运行时才爆出隐蔽问题
def load_resilience_config(
    path: Path,
) -> ResilienceConfig:
    document = json.loads(
        path.read_text(encoding="utf-8")
    )

    operations = {}

    for name, payload in (
        document.get("operations") or {}
    ).items():
        operation = OperationPolicy(
            name=str(name),
            timeout=parse_timeout(
                payload["timeout"]
            ),
            retry=parse_retry(
                payload["retry"]
            ),
            fallback=parse_fallback(
                payload["fallback"]
            ),
            rate_limit=parse_rate_limit(
                payload["rate_limit"]
            ),
            idempotency=parse_idempotency(
                payload["idempotency"]
            ),
        )
        validate_operation(operation)
        operations[name] = operation

    if not operations:
        raise ValueError(
            "resilience 配置没有 operations"
        )

    return ResilienceConfig(
        operations=operations
    )

### 3. 合法性校验 `validate_operation`

# 这是生产级配置的必备设计，对每个操作的所有策略做边界校验，非法配置直接在加载阶段抛出错误。
def validate_operation(
    operation: OperationPolicy,
) -> None:
    name = operation.name

    if operation.timeout.timeout_ms <= 0:
        raise ValueError(
            f"{name}: timeout_ms 必须大于 0"
        )

    retry = operation.retry

    if retry.max_attempts < 1:
        raise ValueError(
            f"{name}: max_attempts 必须大于等于 1"
        )

    if retry.base_delay_ms < 0:
        raise ValueError(
            f"{name}: base_delay_ms 不能为负"
        )

    if retry.max_delay_ms < retry.base_delay_ms:
        raise ValueError(
            f"{name}: max_delay_ms "
            "不能小于 base_delay_ms"
        )

    if not 0.0 <= retry.jitter_ratio <= 1.0:
        raise ValueError(
            f"{name}: jitter_ratio 必须在 0 到 1"
        )

    rate_limit = operation.rate_limit

    if rate_limit.enabled:
        if rate_limit.limit <= 0:
            raise ValueError(
                f"{name}: rate limit 必须大于 0"
            )
        if rate_limit.window_seconds <= 0:
            raise ValueError(
                f"{name}: rate window 必须大于 0"
            )
        if not rate_limit.key_template:
            raise ValueError(
                f"{name}: 缺少 rate limit key_template"
            )

    idempotency = operation.idempotency

    if (
        idempotency.enabled
        and not idempotency.key_template
    ):
        raise ValueError(
            f"{name}: 缺少 idempotency key_template"
        )

    if idempotency.ttl_seconds <= 0:
        raise ValueError(
            f"{name}: idempotency ttl 必须大于 0"
        )

#### 校验规则一览

# 表格

# | 策略 | 校验项 | 目的 |
# | --- | --- | --- |
# | 超时 | `timeout_ms > 0` | 避免 0 或负超时导致逻辑异常 |
# | 重试 | `max_attempts >= 1` | 至少尝试 1 次，否则逻辑无意义 |
# | 重试 | `base_delay_ms >= 0` | 延迟不能为负 |
# | 重试 | `max_delay_ms >= base_delay_ms` | 最大延迟不能小于基础延迟 |
# | 重试 | `0 <= jitter_ratio <= 1` | 抖动比例在合法范围 |
# | 限流 | 启用时 `limit > 0`、`window_seconds > 0` | 限流参数合法 |
# | 限流 | 启用时必须有 `key_template` | 没有 key 无法做限流计数 |
# | 幂等 | 启用时必须有 `key_template` | 没有 key 无法做幂等判断 |
# | 幂等 | `ttl_seconds > 0` | 过期时间必须合法 |

# > 
# > 设计思想：**失败快**。配置错误越早发现，排查成本越低。如果等到运行时才触发，很可能造成难以定位的生产故障。


### 2. 和现有体系的衔接

# - **上游**：纯配置文件，开发 / 运维可编辑，支持环境差异化配置
# - **下游**：S17-2~S17-5 的弹性执行器，按策略执行超时控制、重试退避、降级熔断、限流、幂等
# - **和仓储层联动**：执行器会基于配置，调用你之前的 `ToolCallRepository`、`IdempotencyRepository`，自动记录重试次数、执行幂等校验、更新工具状态

# ---

# ## 五、核心设计价值

# 1. **策略与执行解耦**：容错规则和业务逻辑完全分开，改策略不用动代码
# 2. **强类型安全**：JSON 弱类型转成强类型对象，后续执行逻辑不用到处做类型判断和转换
# 3. **配置即校验**：加载阶段拦截所有非法配置，避免运行时出现难以复现的边界问题
# 4. **细粒度控制**：每个操作独立配置策略，可以针对不同工具的特性定制容错等级
# 5. **可扩展性强**：后续加新的策略（比如熔断），只需要加对应的解析函数和校验规则，不影响现有逻辑