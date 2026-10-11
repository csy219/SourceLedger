# 这段代码完整实现了**滑动窗口限流算法**的两套工程化实现：**本地线程安全版**和**Redis 分布式全局版**，
# 两者遵循完全一致的调用接口，可根据部署场景无缝切换。下面我逐模块拆解逻辑、设计意图和底层原理。


# 导入项	作用
# threading	提供线程锁能力，给本地限流器做多线程并发保护
# time	提供时间计算能力，是滑动窗口的时间基准
# uuid	生成全局唯一 ID，保证 Redis 有序集合里每条请求记录不重复
# defaultdict	字典的变种，访问不存在的 key 时自动创建默认值（这里自动创建空队列），省去手动初始化判断
# deque	双端队列，队头弹出、队尾追加都是 O(1) 效率，远高于普通列表的 pop(0)，是滑动窗口的核心数据结构
# dataclass	装饰器，快速定义数据类，自动生成 __init__、__repr__ 等方法，减少样板代码
# Any	类型注解标记，代表任意类型，这段代码里实际未使用，属于预留导入
# Redis	Redis 官方 Python 客户端的核心类，用来建立连接、执行 Redis 命令导入项	作用
# threading	提供线程锁能力，给本地限流器做多线程并发保护
# time	提供时间计算能力，是滑动窗口的时间基准
# uuid	生成全局唯一 ID，保证 Redis 有序集合里每条请求记录不重复
# defaultdict	字典的变种，访问不存在的 key 时自动创建默认值（这里自动创建空队列），省去手动初始化判断
# deque	双端队列，队头弹出、队尾追加都是 O(1) 效率，远高于普通列表的 pop(0)，是滑动窗口的核心数据结构
# dataclass	装饰器，快速定义数据类，自动生成 __init__、__repr__ 等方法，减少样板代码
# Any	类型注解标记，代表任意类型，这段代码里实际未使用，属于预留导入
# Redis	Redis 官方 Python 客户端的核心类，用来建立连接、执行 Redis 命令
import threading
import time
import uuid
from collections import defaultdict,deque
from dataclasses import dataclass
from typing import Any

from redis import Redis


# 二、RateLimitResult：统一限流结果数据类
### 类的整体作用

# 作为**两种限流器统一的返回格式**，屏蔽本地 / Redis 实现的内部差异，调用方不用关心底层是内存还是 Redis，只需要读取这个结果对象即可。

# ### 逐行 / 字段解释

# - `@dataclass(frozen=True)`
#   - `dataclass`：自动生成构造函数、打印方法等，不用手动写 `__init__`
#   - `frozen=True`：冻结实例，创建后不能修改字段值，保证返回结果的不可变性，避免调用方意外篡改结果，也天然线程安全
# - `allowed: bool`：本次请求是否被允许通过（True = 放行，False = 被限流）
# - `remaining: int`：当前时间窗口内，剩余还可以调用的次数
# - `retry_after_seconds: float`：被限流时，距离下一次放行需要等待的秒数；放行时为 0，可直接用于 HTTP 响应头 `Retry-After`
@dataclass(frozen=True)
class RateLimitResult:
    allowed:bool
    remaining:int
    retry_after_seconds:float

# 三、LocalRateLimiter：本地内存滑动窗口限流器
### 类的整体作用

# 基于**进程内存 + 双端队列 + 线程锁**实现的滑动窗口限流器，**仅在当前进程内生效**，适合单体应用、单实例服务。
# ### **init** 构造函数逐变量解释
class LocalRateLimiter:
    def __init__(self)->None:

        # - `self._events`
        #   - 类型：`dict[str, deque[float]]`，键是限流维度（比如 `"user:1001:submit"`、`"api:order:create"`），值是双端队列
        #   - 作用：存储每个限流维度下，所有请求的时间戳；队列里的时间戳按请求先后顺序排列，队头最旧、队尾最新
        #   - `defaultdict(deque)`：访问不存在的 key 时，自动创建一个空的 `deque` 作为值，不用写 `if key not in dict` 的初始化逻辑
        self._events:dict[str,deque[float]]=defaultdict(deque)

        # - `self._lock`
        #   - 类型：`threading.Lock` 线程互斥锁
        #   - 作用：多线程环境下，同一时间可能有多个线程同时操作同一个队列，会出现数据错乱（比如同时弹队头、同时追加）；加锁后保证同一时刻只有一个线程能操作队列，保证并发安全
        self._lock=threading.Lock()

    # check 方法：核心限流判断逻辑
    def check(
        # **参数定义**

        # - `key: str`：限流维度键，用来区分不同的限流对象（比如按用户、按接口、按 IP）
        # - `limit: int`：时间窗口内最多允许的请求次数，也就是限流阈值
        # - `window_seconds: int`：滑动窗口的时间长度，单位秒
        self,
        key:str,
        limit:int,
        window_seconds:int,
    )->RateLimitResult:
        now=time.monotonic()

        # - `cutoff`：窗口的左边界（时间点）
        # - 作用：早于这个时间点的请求都属于「过期请求」，需要从队列里清理掉；只保留 `(cutoff, now]` 这个区间内的请求
        cutoff=now-window_seconds
        # - 获取线程锁，进入临界区；`with` 语法会在代码块结束后自动释放锁，即使报错也会释放
        # - 作用：保证下面的队列清理、计数、追加操作是原子的，多线程下不会出现竞态条件
        with self._lock:
            # 获取当前限流队列
            events=self._events[key]

            # 清理过期请求（滑动窗口核心）
            # - 循环判断队头（最旧的时间戳）是否早于等于窗口左边界
            # - `events.popleft()`：从队头移除过期的时间戳
            # - 这一步就是「滑动窗口」的本质：窗口跟着当前时间向前移动，不断把滑出窗口的旧请求丢掉，只保留窗口内的请求
            while events and events[0]<=cutoff:
                events.popleft()

            # 限流判断：超出阈值则拒绝
            # - `retry_after`：需要等待多久才能有下一次放行机会，单位秒
            # - 计算逻辑：窗口总时长 - 最早的请求已经过去的时长 = 最早的请求还有多久会滑出窗口
            # - `max(0.0, ...)`：兜底保护，防止时间边界问题出现负数
            if len(events)>=limit:
                retry_after=max(
                    0.0,
                    window_seconds-(now-events[0])
                )
                # 返回限流结果：不允许、剩余次数为 0、保留 3 位小数的等待时长
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=round(retry_after)
                )
            # 未超限：放行并记录请求
            events.append(now)
            remaining=max(0,limit-len(events))
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                retry_after_seconds=0.0,
            )

# 四、REDIS_RATE_LIMIT_LUA：Redis 限流原子脚本
### 脚本整体作用
# 把「清理过期请求 → 统计数量 → 判断限流 → 写入请求」整个流程封装成 Lua 脚本，**在 Redis 单线程中原子执行**，彻底避免分布式并发下的竞态条件，保证限流精确性。

# > 为什么必须用 Lua？如果拆成多条独立命令，并发下两个请求可能同时查到数量刚好差 1，都判断为放行，最终实际流量超过阈值。Lua 脚本在 Redis 中是一个整体执行，中间不会插入其他客户端命令。

# 1.
# - `key`Redis 中的限流键，对应本地版的 `key`
# - Redis 规范中，操作的 key 必须放在 `KEYS` 数组里，参数放在 `ARGV` 里，兼容 Redis 集群的路由规则

# 2.
# - `now_ms`：当前时间，毫秒级整数
# - `tonumber()`：转成数字类型，Lua 接收的参数默认是字符串

# 3.
# - `member`：本次请求的唯一标识，作为 ZSET（有序集合）的成员值
# - 为什么不用时间戳当 member？同一毫秒可能有多个请求，用时间戳会被覆盖，加上 UUID 保证每条请求都是唯一元素

# 4.
# `cutoff`：窗口左边界，毫秒级；早于这个时间的请求都属于过期

# 5.
# - 调用 Redis 命令 `ZREMRANGEBYSCORE`
# - 作用：删除有序集合中分数（score）在 0 到 cutoff 之间的所有元素，也就是清理所有过期的请求记录
# - ZSET 的 score 存的就是请求时间戳，按分数删除就是按时间删除

# 6.
# - `count`：当前有序集合的元素数量，也就是当前窗口内的有效请求总数
# - `ZCARD`：统计 ZSET 元素个数的命令

# 7.
# 如果当前请求数达到阈值，返回 0 代表「不允许」

# 8.
# - 调用 `ZADD` 命令，把本次请求写入有序集合
# - score = 当前时间毫秒，member = 唯一标识

# 9.
# - 调用 `PEXPIRE` 命令，给这个限流 key 设置过期时间，时长等于窗口时长
# - 作用：如果这个限流维度很久没人访问，到期自动删除，不占用 Redis 内存
# - 为什么过期时间是窗口时长？超过一个窗口后，里面的记录全都会过期，整个 key 没有保留价值

# 10.
# 返回 1 代表「允许通过」

REDIS_RATE_LIMIT_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

local cutoff = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)

local count = redis.call('ZCARD', key)
if count >= limit then
    return 0
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return 1
"""

            
# 五、RedisRateLimiter：分布式滑动窗口限流器
# 基于 **Redis 有序集合 + Lua 原子脚本** 实现的分布式限流器，
# **所有服务实例共享同一个 Redis 计数器**，多实例部署下依然能精准全局限流。
class RedisRateLimiter:

    # - `client: Redis`：传入一个 Redis 客户端实例（依赖注入，方便测试和替换连接）
    # - `self.client`：保存 Redis 客户端连接
    # - `self._script`
    # - 预注册的 Lua 脚本对象
    # - `register_script()` 会把脚本发送到 Redis 缓存，生成脚本的 SHA1 摘要；后续调用不用传输整个脚本，只传 SHA 即可，减少网络开销，执行更快
    def __init__(
        self,
        client:Redis,
    )->None:
        self.client=client
        self._script=self.client.register_script(
            REDIS_RATE_LIMIT_LUA
        )


    # check 方法：分布式限流判断
    def check(
        self,
        key:str,
        limit:int,
        window_seconds:int,
    )->RateLimitResult:
        # - `now_ms`：当前时间戳，转成毫秒整数
        # - 分布式场景下用系统时间，业务场景下时间同步误差可忽略；极致精确可以改用 Redis 自身的 `TIME` 命令
        now_ms=int(time.time()*1000)
        window_ms=window_seconds*1000

        # - `member`：本次请求的唯一标识
        # - 格式：`时间毫秒:uuid十六进制`，既保留时间信息，又保证同一毫秒的请求不重复
        member=f"{now_ms}:{uuid.uuid4().hex}"

        # 执行 Lua 原子脚本
        # - 调用预注册的 Lua 脚本，传入 key 和四个参数
        # - 返回值转成整数：1 = 允许，0 = 拒绝
        allowed=int(
            self._script(
                keys=[key],
                args=[now_ms,window_ms,limit,member],
            )
        )

        # 分支 1：请求放行
        if allowed==1:
            count=int(self.client.zcard(key))
            return RateLimitResult(
                allowed=True,
                remaining=max(0,limit-count),
                retry_after_seconds=0.0,
            )
        # 分支 2：被限流，计算等待时间
        # - `oldest`：窗口内最早的一条请求记录
        # - `zrange(0, 0)`：取索引 0 到 0 的元素，也就是分数最小（时间最早）的元素
        # - `withscores=True`：同时返回元素的分数（也就是请求时间戳）
        # - 返回格式：`[(member, score), ...]`，所以取 `oldest[0][1]` 就是最早请求的时间戳
        oldest=self.client.zrange(
            key,
            0,
            0,
            withscores=True,
        )

        # - `retry_after`：距离下一次放行的等待秒数
        # - 极端兜底：如果 `oldest` 为空（比如刚好全部过期），默认等待一个完整窗口时长
        # - 正常逻辑：窗口总时长 - 最早请求已过去的时长 = 最早请求还有多久滑出窗口，最后除以 1000 转成秒
        retry_after=(
            window_seconds
            if not oldest
            else max(
                0.0,
                (window_ms-(now_ms-int(oldest[0][1]))) / 1000.0,
            )
        )
        # 返回限流结果，保留 3 位小数
        return RateLimitResult(
            allowed=False,
            remaining=0,
            retry_after_seconds=round(retry_after,3)
        )

## 整体设计总结

# 两个限流器**接口完全一致**，遵循同一套返回契约，业务代码可以根据部署场景无缝切换：

# - 单实例开发 / 测试 → 用 `LocalRateLimiter`，无依赖、性能极高
# - 分布式多实例部署 → 用 `RedisRateLimiter`，全局精准限流

# 本地数据流
# 请求到达
#     |
#     v
# 按 key 计算时间窗口
#     |
#     v
# 删除窗口外事件
#     |
#     v
# 当前事件数 >= limit？
#     |是
#     v
# 拒绝并返回 retry_after
#     |
#     |否
#     v
# 记录本次请求并返回 allowed=True

# Redis 版本使用：
# Sorted Set
# ZREMRANGEBYSCORE
# ZCARD
# ZADD
# PEXPIRE
# Lua 原子执行
