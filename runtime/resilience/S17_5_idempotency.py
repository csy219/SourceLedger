# 逐行代码全解析：两级幂等执行服务

# 这段代码是**幂等性模块的业务服务层**，基于底层仓储实现了两套独立的幂等控制：

# - **请求级幂等**（`RequestIdempotencyService`）：针对整个业务请求，保证相同请求重复调用只执行一次
# - **工具级幂等**（`ToolExecutionService`）：针对单次工具调用，保证相同工具调用重复触发只执行一次，同时自带重试次数管控

# 两者都遵循「先查状态 → 已存在则按状态处理 / 不存在则执行 → 持久化结果」的标准幂等模式，下面逐行拆解每个变量、类、函数的作用和设计意图。

import json
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Generic,
    TypeVar,
)
# 工具调用的记录结构、状态枚举，是工具级幂等的输入和状态标准
from runtime.S15_state_reference import (
    ToolCallRecord,
    ToolCallStatus,
)
# 通用操作状态枚举（STARTED/SUCCEEDED/FAILED），用于请求级幂等的状态
from runtime.S15_transition_reference import (
    OperationStatus,
)
# 请求级幂等的仓储层和数据摘要，负责数据库读写
from runtime.db.S16_4_idempotency_repository import (
    IdempotencyRepository,
    IdempotencySummary,
)
# 工具级幂等的仓储层和数据摘要，负责数据库读写
from runtime.db.S16_4_tool_call_repository import (
    ToolCallRepository,
    ToolCallSummary,
)

T=TypeVar("T")

# **`RequestInProgress`**
# - 场景：请求级幂等中，相同 key 的请求已经在执行中时抛出
# - 作用：精准区分「请求正在执行」和其他错误，调用方可以据此做等待、重试或直接拒绝
class RequestInProgress(RuntimeError):
    pass


# **`ToolExecutionInProgress`**
# - 场景：工具级幂等中，相同工具调用已经在执行中时抛出
# - 作用：区分工具执行状态，避免重复提交正在运行的工具调用
class ToolExecutionInProgress(RuntimeError):
    pass


# **`ToolRetryExhausted`**
# - 场景：工具调用失败次数已达上限，不允许再重试时抛出
# - 作用：标记重试耗尽状态，上层可以据此做降级、告警等处理
class ToolRetryExhausted(RuntimeError):
    pass

# 设计意图：不直接用通用 `RuntimeError`，而是按错误场景细分异常类，
# 调用方可以按异常类型做精确的分支处理，而不用靠错误字符串判断。


# 1. RequestIdempotencyResult：请求级幂等返回结果
#### 类的整体作用

# 请求级幂等执行的统一返回格式，封装结果数据和执行状态，不可变保证线程安全。

# #### 逐字段解释

# - `key: str`：幂等键，和传入的 key 对应
# - `value: T`：执行结果，泛型 T 支持任意返回类型
# - `replayed: bool`：是否是重放结果；`True`= 之前已经执行过，直接返回历史结果；`False`= 本次真正执行
# - `Generic[T]`：继承泛型基类，绑定类型变量 T
@dataclass(frozen=True)
class RequestIdempotencyResult(Generic[T]):
    key:str
    value:T
    replayed:bool


# 2. ToolExecutionResult：工具级幂等返回结果
# - `tool_call_id: str`：工具调用唯一 ID
# - `value: T`：工具执行结果，泛型支持任意返回类型
# - `replayed: bool`：是否是重放结果
# - `record: ToolCallSummary`：工具调用的完整摘要记录（状态、重试次数、错误信息等），用于上层判断和日志

# > 
# > 共同设计点：`frozen=True` 冻结实例，创建后不可修改，保证结果的不可变性，避免执行过程中被意外篡改，也天然线程安全。
@dataclass(frozen=True)
class ToolExecutionResult(Generic[T]):
    tool_call_id: str
    value: T
    replayed: bool
    record: ToolCallSummary


# 五、工具函数：JSON 序列化校验
# **执行前置校验**：确保业务函数的返回值可以被序列化为 JSON，避免执行成功了但结果存不进数据库的尴尬
# 为什么要做这个校验？
# 幂等的核心是「结果可重放」，结果必须持久化到数据库。如果返回了自定义对象、函数、字节流等不可序列化的值，执行成功后仓储层存失败，就会出现「执行了但没记录」的情况，下次调用还会重新执行，幂等就失效了。
def ensure_json_serializable(
    value: Any,
) -> None:
    try:
        json.dumps(
            value,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "幂等结果必须可序列化为 JSON"
        ) from exc

# 六、RequestIdempotencyService：请求级幂等服务
### 类的整体作用
# 面向业务请求的幂等服务，基于数据库实现**请求级别的去重**，保证同一个幂等 key 对应的业务逻辑只执行一次，重复请求直接返回历史结果。
class RequestIdempotencyService:

    # ### **init** 构造函数
    # - `repository: IdempotencyRepository`：注入请求幂等仓储实例（依赖注入，方便测试和切换实现）
    # - `self.repository`：保存仓储引用，后续所有数据库操作都通过它完成
    def __init__(
        self,
        repository:IdempotencyRepository
    )->None:
        self.repository=repository

    # execute 方法：核心执行入口
    # 幂等执行的统一入口：传入幂等键、运行 ID、业务函数，自动判断是新建执行还是重放历史结果。
    def execute(
        self,
        # - `key: str`：幂等键，唯一标识一个业务请求（比如订单号、请求流水号）
        # - `run_id: str`：本次运行的追踪 ID，用于日志和关联
        # - `func: Callable[[], T]`：真正的业务逻辑函数，无参数，返回泛型 T
        # - `retry_failed: bool = False`：是否允许重试之前失败的请求；默认不允许，失败了就是失败，重复请求直接报错
        key:str,
        run_id:str,
        func:Callable[[],T],
        retry_failed:bool=False,
    )->RequestIdempotencyResult[T]:

        # - 调用仓储层的 `begin` 方法，原子性地「查询或创建」幂等记录
        # - `summary`：幂等记录摘要（状态、结果、错误等）
        # - `created`：布尔值，`True`= 本次新建了记录（第一次执行），`False`= 记录已存在（重复请求）
        # - 这一步是幂等的核心原子操作：保证并发下同一个 key 只有一个请求能创建成功，其他的都拿到已有记录
        summary,created=self.repository.begin(
            key=key,
            run_id=run_id
        )
        if not created:
            return self._handle_existing(
                summary,
                func,
                retry_failed,
            )
        return self._execute_new(
            key=key,
            func=func
        )


    # _handle_existing 方法：处理已存在的记录
    def _handle_existing(
        self,
        summary:IdempotencySummary,
        func:Callable[[],T],
        retry_failed:bool,
    )->RequestIdempotencyResult[T]:
        
        # 1. **状态：成功（SUCCEEDED）**
        # - 直接返回历史结果，标记 `replayed=True`
        # - 这就是幂等的核心价值：重复请求不执行业务逻辑，直接返回上次的结果
        if summary.status==(OperationStatus.SUCCEEDED):
            return RequestIdempotencyResult(
                key=summary.key,
                value=summary.result,
                replayed=True,
            )

        # 2. **状态：执行中（STARTED）**
        # - 抛出 `RequestInProgress` 异常
        # - 说明有另一个请求正在执行这个 key，避免重复执行，也防止并发覆盖
        if summary.status==(OperationStatus.STARTED):
            raise RequestInProgress(
                f"请求正在执行:{summary.key}"
            )

        # 4. **状态：失败（FAILED）**
        # - 如果 `retry_failed=False`（默认）：直接抛出异常，告知之前已经失败过
        # - 如果 `retry_failed=True`：不报错，继续往下走，重新执行
        # - 设计意图：失败的请求是否可重试由业务决定，默认不可重试，保证失败状态的幂等性
        if summary.status==(OperationStatus.FAILED):
            if not retry_failed:
                raise RuntimeError(
                    f"请求之前已经失败: "
                    f"{summary.key}, "
                    f"error={summary.error}")
            
        # 允许重试失败请求时，调用 `_execute_new` 重新执行业务逻辑，覆盖之前的失败记录
        return self._execute_new(
            key=summary.key,
            func=func,
        )
    # _execute_new 方法：执行新请求
    # 真正执行业务函数，成功就持久化结果，失败就持久化错误，保证状态和结果都落库。
    def _execute_new(
        self,
        key:str,
        func:Callable[[],T],
    )->RequestIdempotencyResult[T]:
        # - 调用传入的业务函数，拿到返回值
        # - 立即校验结果是否可序列化，不满足直接抛错，不会继续存库    
        try:
            value=func()
            ensure_json_serializable(value)
        except Exception as exc:
            self.repository.fail(
                key=key,
                error=str(exc),
            )
            raise

        self.repository.complete(
            key=key,
            result=value,
        )
        return RequestIdempotencyResult(
            key=key,
            value=value,
            replayed=False
        )


# 七、ToolExecutionService：工具级幂等服务
# 面向工具调用的幂等服务，比请求级幂等多了**重试次数管控**，保证同一个工具调用重复触发只执行一次，且失败后重试不超过最大次数。
class ToolExecutionService:

    ### **init** 构造函数
    # - `repository: ToolCallRepository`：注入工具调用仓储实例
    # - `self.repository`：保存仓储引用
    def __init__(
        self,
        repository:ToolCallRepository,
    )->None:
        self.repository=repository

    # execute 方法：核心执行入口
    #跟RequestIdempotency上面一样
    def execute(
        self,
        run_id:str,
        record:ToolCallRecord,
        func:Callable[[],T],
    )->ToolExecutionResult[T]:
        summary,created=self.repository.create_or_get(
            run_id=run_id,
            record=record,
        )
        if not created:
            return self._handle_existing(
                run_id=run_id,
                summary=summary,
                record=record,
                func=func,
            )
        return self._execute(
            run_id=run_id,
            tool_call_id=record.tool_call_id,
            func=func,
        )

    # _handle_existing 方法：处理已存在的工具调用
    def _handle_existing(
        self,
        run_id:str,
        summary:ToolCallSummary,
        record:ToolCallRecord,
        func:Callable[[],T],
    )->ToolExecutionResult[T]:

        # **状态：成功（SUCCEEDED）**
        # - 直接返回历史结果，`replayed=True`
        # - 工具调用幂等的核心：相同的 tool_call_id 重复调用，不重复执行工具，直接返回上次
        if summary.status==ToolCallStatus.SUCCEEDED:
            return ToolExecutionResult(
                tool_call_id=summary.tool_call_id,
                value=summary.result,
                replayed=True,
                record=summary
            )

        # **状态：待处理 / 运行中（PENDING / RUNNING）**
        # - 抛出 `ToolExecutionInProgress` 异常
        # - 说明工具已经在执行队列里或者正在跑，避免重复提交
        if summary.status in {
            ToolCallStatus.PENDING,
            ToolCallStatus.RUNNING,
        }:
            raise ToolExecutionInProgress(
                f"工具正在执行: "
                f"{summary.tool_call_id}"
            )

        # 状态：失败且重试次数耗尽
        if (
            summary.attempt
            >= summary.max_attempts
        ):
            raise ToolRetryExhausted(
                f"工具重试次数耗尽: "
                f"{summary.tool_call_id}"
            )

        # **兜底：可以重试，继续执行**
        # - 失败了但还没到最大重试次数，调用 `_execute` 再次执行工具
        # - 执行时仓储层会自动累加重试次数
        return self._execute(
            run_id=run_id,
            tool_call_id=record.tool_call_id,
            func=func,
        )

    # _execute 方法：执行工具调用
    def _execute(
        self,
        run_id: str,
        tool_call_id: str,
        func: Callable[[], T],
    ) -> ToolExecutionResult[T]:
        
        # 标记为运行中
        # - 执行前先把状态更新为 RUNNING，同时累加尝试次数
        # - 防止并发下多个请求同时执行同一个工具调用      
        self.repository.mark_running(
            run_id=run_id,
            tool_call_id=tool_call_id,
        )
        try:
            value = func()
            ensure_json_serializable(value)
        # 异常分支 1：超时错误
        except TimeoutError as exc:
            self.repository.mark_failed(
                run_id=run_id,
                tool_call_id=tool_call_id,
                status=ToolCallStatus.TIMED_OUT,
                error=str(exc),
            )
            raise
        # 异常分支 2：普通错误
        except Exception as exc:
            self.repository.mark_failed(
                run_id=run_id,
                tool_call_id=tool_call_id,
                status=ToolCallStatus.FAILED,
                error=str(exc),
            )
            raise
        # 成功分支：标记成功
        summary = self.repository.mark_succeeded(
            run_id=run_id,
            tool_call_id=tool_call_id,
            result=value,
        )
        # 返回工具执行结果，`replayed=False`，附带完整记录摘要
        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            value=value,
            replayed=False,
            record=summary,
        )

## 整体设计总结

### 1. 两层幂等的定位与关系

# - **请求级幂等**：粗粒度，面向整个业务请求，防重复提交、防重复回调
# - **工具级幂等**：细粒度，面向单次工具调用，防重复执行工具、管控重试次数
# - 关系：一个请求里可能包含多次工具调用，请求级幂等在外层，工具级幂等在内层，共同保证整条链路的幂等性

# ### 2. 核心设计原则

# - **状态先行**：先创建 / 查询记录，再执行业务，保证任何情况都有迹可循
# - **原子落库**：依赖仓储层的原子操作，避免并发下重复创建
# - **异常落库**：失败也必须更新状态，不能只在成功时落库，否则失败场景幂等失效
# - **结果可序列化**：强制校验 JSON 序列化，保证结果能完整持久化和重放
# - **依赖注入**：仓储通过构造注入，方便单元测试和切换存储实现