# 下面逐行逐段拆解这段熔断器（Circuit Breaker）代码，完整说明
# 每个类、函数、变量的作用和设计目的，和上一段的分析格式保持一致。

# - 作用：导入 Python 标准库 `threading` 模块
# - 用途：后续创建互斥锁 `Lock`，保证多线程环境下熔断器状态修改的原子性，避免竞态条件导致计数错乱、状态异常
import threading 

# - 作用：导入 Python 标准库 `time` 模块
# - 用途：使用 `time.monotonic()` 单调时钟计算时间间隔，不受系统时间回拨 / 调整的影响，精准计算熔断时长、恢复超时
import time


# - 作用：导入枚举基类 `Enum`
# - 用途：定义熔断器的三种状态枚举，保证状态取值合法、代码可读性强，避免魔法字符串
from enum import Enum



# 作用：导入两个类型注解工具
# - `Callable`：标注可调用对象（函数、方法）的类型
# - `TypeVar`：声明泛型类型变量，让熔断器支持任意返回值类型的函数
from typing import Callable,TypeVar


# - 变量名：`T`
# - 类型：泛型类型变量
# - 作用：代表「任意一种返回值类型」，让熔断器的 `call` 方法可以包装任意返回类型的业务函数，同时保持类型检查的一致性
T=TypeVar("T")


# 三、CircuitState 状态枚举
# 定义熔断器的三种核心状态，继承 `str` 让枚举值可以直接当字符串使用，继承 `Enum` 保证类型安全，避免非法状态值。

### 逐字段说明

# - `CLOSED = "closed"`：**闭合状态**
#   - 正常工作状态，所有请求都放行，同时累计连续失败次数
#   - 失败次数达到阈值后，自动切换到 OPEN 熔断状态
# - `OPEN = "open"`：**打开（熔断）状态**
#   - 故障保护状态，所有请求直接被拒绝，不调用下游服务
#   - 核心目的：防止下游服务故障时，大量请求持续施压导致雪崩
#   - 持续 `recovery_timeout_seconds` 时间后，自动切换到 HALF_OPEN 半开状态
# - `HALF_OPEN = "half_open"`：**半开状态**
#   - 恢复试探状态，只允许极少量请求通过做健康探测
#   - 若试探请求成功：切回 CLOSED 状态，正式恢复服务
#   - 若试探请求失败：立刻切回 OPEN 状态，继续熔断
class CircuitState(str,Enum):
    CLOSED="closed"
    OPEN="open"
    HALF_OPEN="half_open"



# 四、CircuitOpenError 自定义异常

### 类的整体作用
# 熔断器处于打开状态、或半开状态请求已满时抛出的运行时异常，告诉调用方当前服务被熔断，以及多久后可以重试。
# ### 逐行说明

# - `class CircuitOpenError(RuntimeError):`
#   - 继承 `RuntimeError`，属于运行时异常，符合 Python 异常体系规范
# - `def __init__(self, name, retry_after_seconds):`
#   - 构造方法，接收熔断器名称和剩余可重试时间
# - `super().__init__(...)`
#   - 调用父类构造方法，拼接友好的错误提示信息，保留三位小数显示剩余时间
# - `self.name = name`
#   - 保存熔断器名称，调用方捕获异常后可以识别是哪个服务 / 熔断器触发的熔断
# - `self.retry_after_seconds = retry_after_seconds`
#   - 保存距离恢复的剩余秒数，调用方可以根据这个值实现延迟重试、降级等逻辑
class CircuitOpenError(RuntimeError):
    def __init__(
        self,
        name:str,
        retry_after_seconds:float,
    )->None:
        super().__init__(
            f"{name}:熔断中,"
            f"{retry_after_seconds:.3f}s后可重试"
        )
        self.name=name
        self.retry_after_seconds=retry_after_seconds

# 五、CircuitBreaker 熔断器核心类
# 线程安全的熔断器模式实现，通过「失败计数→熔断→试探恢复」的状态机机制，在下游服务故障时快速失败，避免请求堆积拖垮整个系统。
class CircuitBreaker:
    def __init__(
        self,

        # `name: str`：熔断器的唯一标识名称，用于日志、异常中区分不同的服务 / 熔断器
        name:str,

        #     `failure_threshold: int = 5`：失败阈值，默认 5 次
        # - 闭合状态下，连续失败达到这个次数，就触发熔断
        failure_threshold:int=5,

        # `recovery_timeout_seconds: float = 30.0`：熔断恢复超时，默认 30 秒
        # - 熔断器打开后，经过这个时长，自动进入半开试探状态
        recovery_timeout_seconds:float=30.0,

        # `half_open_max_calls: int = 1`：半开状态最大请求数，默认 1 次
        # - 半开状态下最多允许放行多少个请求做试探，避免大量请求同时试探打挂下游
        half_open_max_calls:int=1,
    )->None:
        if failure_threshold <= 0:
            raise ValueError(
                "failure_threshold 必须大于 0"
            )
        if recovery_timeout_seconds <= 0:
            raise ValueError(
                "recovery_timeout_seconds 必须大于 0"
            )
        if half_open_max_calls <= 0:
            raise ValueError(
                "half_open_max_calls 必须大于 0"
            )
        
        # - 作用：把配置参数保存为实例属性，供后续方法使用
        # - 都是公开的只读配置项
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = (
            recovery_timeout_seconds
        )
        self.half_open_max_calls = (
            half_open_max_calls
        )

        # - 变量名：`_state`
        # - 类型：`CircuitState` 枚举
        # - 作用：记录熔断器当前的状态
        # - 下划线前缀表示私有变量，不希望外部直接修改，必须通过类的方法来变更
        # - 初始值为 `CLOSED`，默认正常工作
        self._state=CircuitState.CLOSED

        # - 作用：闭合状态下的连续失败计数器
        # - 每次业务失败 + 1，成功则清零；达到阈值就触发熔断
        self._failure_count=0

        # - 作用：记录熔断器切换到 OPEN 状态的时间点
        # - 用途：用来计算熔断已经持续了多久，判断是否到了恢复超时时间
        self._opened_at=0.0

        # - 作用：半开状态下已放行的请求计数器
        # - 用途：控制半开状态的试探请求数量，不超过 `half_open_max_calls`
        self._half_open_calls=0

        # - 类型：`threading.Lock` 互斥锁
        # - 作用：保证多线程环境下，所有状态读写、计数修改都是原子操作
        # - 目的：防止多线程同时修改状态导致计数不准、状态错乱
        self._lock=threading.Lock()

    # 2. state 只读属性
    # - 作用：对外提供只读的当前状态查询
    # - 逻辑：
    # 1. 加锁保证线程安全
    # 2. 先调用 `_transition_if_needed` 检查是否需要做状态转换（比如熔断超时了转半开）
    # 3. 返回最新的状态
    # - 设计目的：外部获取状态时，自动触发状态转换检查，保证拿到的一定是最新的正确状态
    @property
    def state(self)->CircuitState:
        with self._lock:
            self._transition_if_needed(
                time.monotonic()
            )
            return self._state

    # 3. _transition_if_needed 状态转换检查（私有方法）
    # - 作用：检查并执行「OPEN → HALF_OPEN」的自动状态转换
    # - 入参 `now`：当前的单调时间戳，由调用方传入，避免重复获取时间
    def _transition_if_needed(
        self,
        now:float,
    )->None:
        if self._state!=CircuitState.OPEN:
            return 

        # 作用：计算熔断器已经处于打开状态的时长（秒）
        elapsed=now-self._opened_at
        # 逻辑：如果熔断时长已经超过恢复超时时间
        # 1. 把状态切换为 HALF_OPEN 半开状态
        # 2. 重置半开请求计数器为 0，准备试探
        if elapsed >= self.recovery_timeout_seconds:
            self._state=CircuitState.HALF_OPEN
            self._half_open_calls=0

    # 4. _open 打开熔断器（私有方法）
    # - 作用：将熔断器切换为打开（熔断）状态
    # - 执行三个操作：
    # 1. 设置状态为 OPEN
    # 2. 记录当前时间为熔断开始时间
    # 3. 重置失败计数器，为下次恢复后的计数做准备
    # - 设计目的：抽离公共的熔断逻辑，避免重复代码
    def _open(self,now:float)->None:
        self._state=CircuitState.OPEN
        self._opened_at=now
        self._failure_count=0

    # 5. _before_call 请求前置检查（私有方法
    # - 作用：在执行业务函数之前调用，做熔断状态检查和放行控制
    # - 这是熔断器的核心拦截逻辑：熔断状态下直接拒绝请求，不执行业务代码
    def _before_call(self)->None:
        # 获取当前单调时间戳，后续计算时间差都用这个值
        now=time.monotonic()

        # 加锁，保证整个检查 + 状态修改的原子性
        with self._lock:
            # 先做状态转换检查，确保当前状态是最新的
            self._transition_if_needed(now)

            # 逻辑：如果当前是熔断打开状态
            # 1. 计算距离恢复的剩余时间，用 `max(0.0, ...)` 避免出现负数
            # 2. 抛出 `CircuitOpenError` 异常，直接拒绝请求，不执行业务函数
            if self._state == CircuitState.OPEN:
                remaining=max(
                    0.0,
                    self.recovery_timeout_seconds-(now-self._opened_at)
                )
                raise CircuitOpenError(
                    self.name,
                    remaining
                )

            # - 逻辑：如果当前是半开状态
            # 1. 检查已放行的试探请求数是否达到上限
            # 2. 如果达到上限：同样抛出熔断异常，拒绝请求
            # 3. 如果没达到上限：半开请求数 + 1，放行这个请求
            if self._state==CircuitState.HALF_OPEN:
                if(self._half_open_calls >= self.half_open_max_calls):
                    raise CircuitOpenError(
                        self.name,
                        self.recovery_timeout_seconds,
                    )
                self._half_open_calls+=1

    # 6. record_success 记录成功
    # - 作用：业务函数执行成功时调用，标记一次成功
    # - 执行操作：
    # 1. 状态切回 CLOSED 正常闭合
    # 2. 清零失败计数器
    # 3. 清零半开请求计数器
    # - 适用场景：
    # - 闭合状态下成功：维持闭合，清零失败计数
    # - 半开状态下成功：说明服务恢复了，正式恢复到闭合状态
    def record_success(self)->None:
        with self._lock:
            self._state=CircuitState.CLOSED
            self._faliure_count=0
            self._half_open_calls=0


    # 7. record_failure 记录失败
    def record_failure(self)->None:
        now=time.monotonic()

        with self._lock:
            # 逻辑：如果当前是半开状态
            # - 只要试探请求失败，立刻重新打开熔断器（调用 `_open`）
            # - 说明下游服务还没恢复，继续熔断
            # - 直接返回，不用走下面的计数逻辑
            if self._state==CircuitState.HALF_OPEN:
                self._open(now)
                return

            # - 逻辑：如果不是闭合状态（也就是已经是打开状态），直接返回
            # - 目的：打开状态下请求本来就被拦截了，不会走到这里，做个防御性判断
            if self._state!=CircuitState.CLOSED:
                return

            # 闭合状态下，失败计数器 + 1
            self._failure_count+=1

            # 逻辑：如果失败次数达到熔断阈值
            # - 调用 `_open` 打开熔断器，进入熔断状态
            if(self._failure_count>=self.failure_threshold):
                self._open(now)
    
    # 8. call 执行包装方法
    # - 作用：熔断器的核心入口方法，包装业务函数，自动做熔断控制、成功 / 失败记录
    # - 入参 `func`：无参的业务函数，返回类型为 `T`
    # - 返回值：业务函数的执行结果，类型为 `T`
    def call(
        self,
        func:Callable[[],T],
    )->T:
        # - 第一步：执行前置检查
        # - 如果熔断中，这里会直接抛异常，不会执行业务函数
        self._before_call()

        # 逻辑：尝试执行业务函数
        # - 如果抛出任何异常：调用 `record_failure` 记录失败，然后把异常重新抛出给调用方
        # - 注意：这里捕获所有异常，只要业务抛异常就算失败
        try:
            result=func()
        except Exception:
            self.record_failure()
            raise

        # 逻辑：业务函数执行成功
        # - 调用 `record_success` 记录成功，恢复状态
        # - 返回业务函数的执行结果
        self.record_success()
        return result
        

#***********************************************************************
## 整体执行流程总结

# 1. **正常阶段（CLOSED）**：请求全部放行，失败累计计数，成功清零计数；失败达到阈值→触发熔断
# 2. **熔断阶段（OPEN）**：所有请求直接抛异常，不调用下游；持续超时后→自动进入半开
# 3. **试探阶段（HALF_OPEN）**：只放行少量请求；成功→恢复正常；失败→立刻重新熔断
# 4. **线程安全**：所有状态读写都通过锁保护，多线程环境下逻辑正确
# CLOSED：
# 正常放行。
# 连续失败达到阈值后进入 OPEN。

# OPEN：
# 直接拒绝调用，不继续打下游。

# HALF_OPEN：
# 恢复时间到后允许少量探测请求。
# 成功则回到 CLOSED。61
# 失败则重新进入 OPEN。