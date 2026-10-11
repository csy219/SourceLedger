# 这是一段**弹性容错机制的测试 / 演示脚本**，完整验证两个核心组件的行为：

# 1. **降级链（Fallback Chain）**：主逻辑失败后，按顺序依次尝试备用方案，全部失败则抛出耗尽异常
# 2. **熔断器（Circuit Breaker）**：连续失败达到阈值后熔断，冷却后半开试探，成功则恢复闭合

# 脚本最终会把所有测试结果整理为 JSON 格式打印输出。

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from runtime.resilience.S17_3_circuit_breaker import(
    CircuitBreaker,
    CircuitOpenError,
)

from runtime.resilience.S17_3_fallback import(
    FallbackExhausted,
    execute_with_fallback,
)

def main()->int:
    # 测试 1：正常降级链（主失败 → 降级成功）
    # 定义主执行函数，直接抛出连接错误，模拟主服务不可用。
    def primary_fail() -> str:
        raise ConnectionError(
            "primary unavailable"
        )

    # 调用降级执行器，参数说明：

    # - `primary_name`：主逻辑标识名
    # - `primary`：主执行函数（这里一定会失败）
    # - `fallback_chain`：降级链的执行顺序，先尝试 `bm25_only`，失败再试 `cached_retrieval`
    # - `handlers`：每个降级名称对应的执行函数

    # 执行流程：
    # 主函数 `primary_fail` 抛出异常 → 触发降级 → 第一个降级 `bm25_only` 执行成功 → 返回结果，终止降级链。
    # 最终 `fallback` 对象会包含：成功来源、每一步尝试的详情（成功 / 失败）。
    fallback = execute_with_fallback(
        primary_name="primary",
        primary=primary_fail,
        fallback_chain=(
            "bm25_only",
            "cached_retrieval",
        ),
        handlers={
            "bm25_only": lambda: "bm25 result",
            "cached_retrieval": (
                lambda: "cached result"
            ),
        },
    )
    # 测试 2：降级耗尽（主失败 + 所有降级都失败
    # 验证「所有降级全部失败」的场景：

    # - 降级链只有一个 `also_fail`，对应的 handler 会抛出异常
    # - 这里用了一个 Python 技巧：`(_ for _ in ()).throw(...)`
    # > 
    # > lambda 表达式里不能直接写 `raise` 语句，因此构造一个空生成器，调用生成器的 `throw` 方法抛出异常，实现在 lambda 里抛异常的效果
    # - 主逻辑失败 + 唯一降级也失败 → 抛出 `FallbackExhausted`（降级耗尽异常）
    # - 捕获异常后，把异常类名 `FallbackExhausted` 存入 `exhausted_error`
    exhausted_error = ""
    try:
        execute_with_fallback(
            primary_name="primary",
            primary=primary_fail,
            fallback_chain=("also_fail",),
            handlers={
                "also_fail": (
                    lambda: (
                        (_ for _ in ()).throw(
                            RuntimeError("also failed")
                        )
                    )
                )
            },
        )
    except FallbackExhausted as exc:
        exhausted_error = type(exc).__name__


    # 测试 3：熔断器 - 触发熔断
    breaker = CircuitBreaker(
        name="model-api",
        failure_threshold=2,
        recovery_timeout_seconds=0.05,
        half_open_max_calls=1,
    )
    # 定义失败调用函数，模拟服务调用出错。
    def fail() -> None:
        raise ConnectionError("model down")

    # 连续执行 2 次失败调用：

    # - 第 1 次失败：失败计数 = 1，未达阈值，熔断器保持闭合
    # - 第 2 次失败：失败计数 = 2，达到阈值 → 熔断器触发熔断，状态变为 `OPEN`
    # - 每次都捕获业务异常 `ConnectionError`，只统计失败，不中断测试流程
    for _ in range(2):
        try:
            breaker.call(fail)
        except ConnectionError:
            pass

    # 测试 4：熔断器 - 熔断状态拦截请求
    # 获取熔断状态的枚举值，此时应为 `open`。
    # > 注意访问 `.state` 属性时，会自动执行状态转换检查（就是上一期讲的 `@property` 逻辑）。
    open_state = breaker.state.value


    # 验证熔断状态的拦截效果：

    # - 熔断器处于 OPEN 状态，调用会直接抛出 `CircuitOpenError`
    # - lambda 里的代码**完全不会执行**（`"should not run"` 永远不会返回）
    # - 捕获异常后，把异常名存入 `open_error`
    open_error = ""
    try:
        breaker.call(lambda: "should not run")
    except CircuitOpenError:
        open_error = "CircuitOpenError"

    # 测试 5：熔断器 - 冷却恢复
    time.sleep(0.06)

    # 睡眠 60 毫秒，超过了 50 毫秒的冷却时间，此时访问熔断器状态会自动从 `OPEN` 转为 `HALF_OPEN`（半开）。
    # 半开状态下执行调用：
    # - 半开状态允许 1 次试探调用，请求放行
    # - lambda 执行成功，返回 `"recovered"`
    # - 成功后熔断器会自动调用 `record_success`，状态从半开直接变回 `CLOSED`（闭合，正常状态）
    recovered = breaker.call(
        lambda: "recovered"
    )

    # 获取恢复后的状态，此时应为 `closed`。
    recovered_state = breaker.state.value

    # 把所有测试结果整理成字典：

    # - `fallback_source`：最终成功降级的来源（`bm25_only`）
    # - `fallback_attempts`：所有执行尝试的列表，包含主逻辑和每一级降级
    # - `fallback_exhausted`：降级耗尽的异常名
    # - `breaker_open_state`：熔断时的状态值
    # - `breaker_open_error`：熔断拦截抛出的异常名
    # - `breaker_recovered`：恢复后调用的返回值
    # - `breaker_recovered_state`：恢复后的熔断器状态
    output = {
        "fallback_source": fallback.source,
        "fallback_attempts": [
            {
                "source": item.source,
                "error": item.error,
            }
            for item in fallback.attempts
        ],
        "fallback_exhausted": (
            exhausted_error
        ),
        "breaker_open_state": open_state,
        "breaker_open_error": open_error,
        "breaker_recovered": recovered,
        "breaker_recovered_state": (
            recovered_state
        ),
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())