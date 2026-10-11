import time
from dataclasses import dataclass
from typing import (
    Callable,
    Generic,
    TypeVar,
)
# 这段代码实现了一个**多级降级（Fallback）执行器**，核心作用是按优先级顺序尝试执行主逻辑 
# + 多个备用逻辑，完整记录每一次失败的详情与整体耗时，所有策略都失败时抛出聚合异常。

T=TypeVar("T")

# `FallbackAttempt`：记录单次失败的来源与错误信息
@dataclass(frozen=True)
class FallbackAttempt:
#     `source: str`：
# - 变量作用：存储本次失败的执行源名称（比如主函数名、降级函数名）
# - 用途：用来标识是哪一个策略失败了
    source:str
#     `error: str`：
# - 变量作用：存储本次失败的错误信息
# - 用途：记录失败原因，最终汇总到异常或结果中
    error:str

# `FallbackResult<T>`：泛型结果类，封装成功返回值、成功来源、所有失败尝试、总耗时
@dataclass(frozen=True)
class FallbackResult(Generic[T]):
    value:T
    source:str
    attempts:tuple[FallbackAttempt,...]
    elapsed_ms:float

# `FallbackExhausted`：自定义异常，所有降级都失败时抛出，携带全部失败记录
class FallbackExhausted(RuntimeError):
    def __init__(
        self,
        attempts: tuple[FallbackAttempt, ...],
    ) -> None:
        super().__init__(
            "所有 fallback 均失败: "
            + "; ".join(
                f"{item.source}={item.error}"
                for item in attempts
            )
        )
        self.attempts = attempts

# `execute_with_fallback`：核心执行函数，按顺序尝试主函数与降级链
# 按优先级顺序，先尝试执行主函数；主函数失败后，按顺序逐个尝试降级链里的备用函数；
# 每失败一次就记录详情；任意一个成功就立刻返回结果；全部失败则抛出聚合异常。
def execute_with_fallback(
        
    # 主函数的标识名称，用来在失败记录和结果中标记主逻辑
    primary_name:str,

    # - 主执行函数，无参数，返回 `T` 类型
    # - 这是最高优先级的执行逻辑，会第一个被尝试
    primary:Callable[[],T],

    # - 降级链，字符串元组，每个元素是降级处理器的名称
    # - 顺序就是降级的优先级顺序：排在前面的先尝试
    fallback_chain:tuple[str,...],

    # - 所有降级处理器的字典：key 是处理器名称，value 是对应的执行函数
    # - 降级链里的名字需要在这个字典里才能被执行
    handlers:dict[str,Callable[[],T]],
)->FallbackResult[T]:
    started=time.perf_counter()
    attempts:list[FallbackAttempt]=[]

#     - 变量名：`candidates`
# - 类型：列表，每个元素是 `(名称, 函数)` 的元组
# - 作用：构造「待执行的候选函数列表」，按优先级排序
# - 执行逻辑：
#   1. 第一个元素永远是主函数 `(primary_name, primary)`
#   2. 遍历 `fallback_chain`，只把**存在于 `handlers` 字典里**的降级函数加进来
#   3. 不存在的降级项会被跳过，不在这个候选列表里
    candidates=[
        (primary_name,primary),
        *[
            (
                name,
                handlers[name],
            )
            for name in fallback_chain
            if name in handlers
        ],
    ]

#     - 作用：单独遍历一次降级链，把**不存在的降级处理器**提前记入失败列表
# - 设计逻辑：如果降级链里配置了一个没注册的处理器，直接算一次失败，记录错误为「fallback handler not found」
# - 注意：这一步是**在执行任何函数之前**，就把缺失的降级项全部加入失败记录
    for name in fallback_chain:
        if name not in handlers:
            attempts.append(
                FallbackAttempt(
                    source=name,
                    error="fallback handler not found",
                )
            )
    for source,handler in candidates:
        try:
            value=handler()
        except Exception as exc:
            attempts.append(
                FallbackAttempt(
                    source=source,
                    error=str(exc)
                )
            )
            continue

        elapsed_ms=(time.perf_counter()-started)*1000
        return FallbackResult(
            value=value,
            source=source,
            attempts=tuple(attempts),
            elapsed_ms=round(elapsed_ms,2),
        )
    raise FallbackExhausted(tuple(attempts))


## 整体执行流程总结

# 1. 记录开始时间，初始化失败记录列表
# 2. 构造候选执行列表：主函数 + 所有存在的降级函数
# 3. 先把降级链里不存在的处理器，全部记为失败
# 4. 按顺序逐个执行候选函数：
#    - 失败 → 记录错误，继续下一个
#    - 成功 → 计算耗时，封装结果返回
# 5. 全部失败 → 抛出携带所有失败记录的自定义异常