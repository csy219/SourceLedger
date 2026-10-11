# 逐行代码全解析：Redis 分布式锁


# ``提供时间计算能力，用于**获取锁的超时控制**、**自旋等待间隔**
import time

# 生成全局唯一的锁持有者令牌，是「防止误删他人锁」的核心标识
import uuid

# 类型注解标记，用于下文 `__exit__` 方法中异常回溯栈参数的类型声明
from types import TracebackType
from typing import Any

# Redis 官方 Python 客户端核心类，用来执行 Redis 命令、调用 Lua 脚本
from redis import Redis

### 脚本整体作用

# 把「校验锁的持有者身份 → 身份匹配则删除锁」整个流程封装成 Lua 脚本，**在 Redis 单线程中原子执行**，
# 彻底解决「先 GET 再 DEL」两步操作非原子导致的**误删他人锁**问题。

# 1.
# - `KEYS[1]`：第一个 key 参数，也就是锁的 Redis 键
# - `ARGV[1]`：第一个参数，也就是当前锁持有者的唯一令牌（token）
# - 逻辑：先取出锁对应的值，和传入的令牌对比，**确认这把锁是当前客户端自己加的**，才能执行删除
# - 为什么必须校验？如果不校验直接 DEL：A 拿到锁后业务卡住，锁自动过期了；B 此时拿到了同一把锁；A 恢复后执行 DEL，就会把 B 的锁删掉，导致互斥失效

# 2.
# - 令牌匹配成功，调用 `DEL` 命令删除锁键，释放锁
# - 返回 `DEL` 命令的结果（成功删除返回 1）

# 3.
# - 令牌不匹配（锁不是自己的，或者锁已经过期不存在），返回 0 表示释放失败
# > 核心设计：为什么不用 Python 先 GET 再 DEL？
# > 两步操作之间存在时间差，可能 GET 的时候锁还是自己的，刚要 DEL 的瞬间锁过期了、被别人拿到了，这时候 DEL 就会误删他人的锁。Lua 脚本在 Redis 中是一个整体，中间不会插入其他客户端的命令，保证原子性。

RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


# 三、LockNotAcquired：获取锁失败异常
### 类的整体作用

# 自定义运行时异常，专门表示「获取分布式锁失败」的场景。

# - 上下文管理器模式下，获取锁失败时抛出该异常，业务代码可以精准捕获和处理锁超时的场景
# - 区分普通运行时错误和锁获取失败，便于错误分类和排查
class LockNotAcquired(RuntimeError):
    pass


# 四、DistributedLock：Redis 分布式锁主类
### 类的整体作用
# 基于 Redis 实现的**分布式互斥锁**，支持：

# - 自动过期防死锁
# - 自旋等待 + 超时控制
# - 持有者身份校验防误删
# - 上下文管理器自动释放锁
# 适用于分布式环境下的资源互斥访问（比如库存扣减、定时任务防并发、配置更新串行化）。
class DistributedLock:
#     参数	类型	作用
# client: Redis	Redis 客户端实例	依赖注入，外部传入已建好连接的 Redis 客户端，方便测试和切换连接
# key: str	锁的键名	代表要锁定的资源，比如 lock:order:1001 表示锁定 1001 号订单的操作
# ttl_ms: int	锁过期时间，单位毫秒	锁的最大持有时间，超时自动释放，防止客户端宕机后锁永久死锁
# wait_timeout_ms: int = 0	获取锁等待超时，单位毫秒	尝试获取锁的最长等待时间，默认 0 表示「一次失败直接返回」，不自旋
# retry_interval_ms: int = 50	自旋重试间隔，单位毫秒	每次获取失败后，休眠多久再重试，避免疯狂轮询打爆 Redis
    def __init__(
        self,
        client:Redis,
        key:str,
        ttl_ms:int,
        wait_timeout_ms:int=0,
        retry_interval_ms:int=50,
    )->None:
        if ttl_ms<=0:
            raise ValueError(
                "ttl_ms 必须大于0" 
            )
        if wait_timeout_ms < 0:
            raise ValueError(
                "wait_timeout_ms 不能为负"
            )

        self.client = client
        self.key = key
        self.ttl_ms = ttl_ms
        self.wait_timeout_ms = wait_timeout_ms
        self.retry_interval_ms = (
            retry_interval_ms
        )

        # 每个锁实例生成**唯一的十六进制令牌**，作为锁的持有者标识；释放锁时校验令牌，只能释放自己加的锁
        self.token = uuid.uuid4().hex

        # 状态标记，记录当前实例是否已经成功获取到锁；防止重复释放、未获取就释放等非法操作
        self.acquired = False

    # acquire 方法：获取锁
    #### 方法整体作用

    # 尝试获取分布式锁，支持**自旋等待 + 超时机制**；获取成功返回 `True`，超时失败返回 `False`。
    def acquire(self)->bool:

        # - `deadline`：获取锁的最晚截止时间点，超过这个时间还没拿到锁就判定为超时失败
        # - 用 `time.monotonic()` 单调时间：不受系统时间回拨、NTP 对时影响，计算超时更精准
        deadline=(
            time.monotonic()
            +self.wait_timeout_ms / 1000.0
        )

        # 自旋循环
        while True:
            # 原子加锁核心命令
            # - 调用 Redis 的 `SET` 命令，携带两个关键参数，整个操作是**原子的**：
            # - `nx=True`：`SET if Not eXists`，只有 key 不存在时才设置成功。保证同一时间只有一个客户端能设置成功，也就是只有一个客户端能拿到锁，实现互斥性。
            # - `px=self.ttl_ms`：设置 key 的过期时间，单位毫秒。和 SET 原子执行，避免「先 SET 成功，还没来得及设过期就宕机」导致的永久死锁。
            # - 值设置为 `self.token`：把持有者令牌存入锁中，后续释放时校验身份
            # - 返回值：设置成功返回 `True`（拿到锁），失败返回 `False`（锁已被占用）
            acquired=bool(
                self.client.set(
                    self.key,
                    self.token,
                    nx=True,
                    px=self.ttl_ms,
                )
            )
            # 分支 1：获取成功
            if acquired:
                self.acquired=True
                return True

            # 分支 2：超时判断
            # 当前时间超过截止时间，还没拿到锁，返回失败，结束自旋
            if time.monotonic()>=deadline:
                return False

            # 分支 3：重试等待
            # - 没拿到锁也没超时，休眠指定间隔后再次尝试
            # - 避免无间隔疯狂轮询，减少 Redis 压力和网络开销
            time.sleep(self.retry_interval_ms / 1000.0)

    # release 方法：释放锁
    # 释放分布式锁，**只有锁的持有者才能成功释放**；释放成功返回 `True`，失败返回 `False`
    def release(self)->bool:
        # 如果当前实例根本没拿到过锁，直接返回失败，防止无意义调用和误操作
        if not self.acquired:
            return False

        # 执行原子释放脚本
        # - 调用 `eval` 执行 Lua 释放脚本
        # - 参数 `1`：表示后面的参数里，前 1 个是 KEYS，剩下的是 ARGV
        # - `self.key`：对应脚本里的 `KEYS[1]`，锁的键
        # - `self.token`：对应脚本里的 `ARGV[1]`，持有者令牌
        # - 返回值转整数：1 = 成功释放，0 = 释放失败（锁不存在 / 不是自己的）
        released=int(
            self.client.eval(
                RELEASE_LOCK_LUA,
                1,
                self.key,
                self.token,
            )
        )

        # - 释放成功：更新状态标记为未持有，返回 True
        # - 释放失败：直接返回 False      
        if released==1:
            self.acquired=False
            return True
        return False

    # **enter** 方法：上下文管理器入口
    # 让锁支持 Python `with` 上下文管理器语法，**进入 `with` 代码块时自动获取锁**，获取失败直接抛异常。
    # #### 逐行解释
    # - `if not self.acquire()`：进入时自动调用 `acquire()` 尝试获取锁
    # - `raise LockNotAcquired(...)`：获取失败抛出自定义异常，中断业务代码执行
    # - `return self`：返回锁实例本身，对应 `with lock as l:` 里的 `l`
    def __enter__(self) -> "DistributedLock":
        if not self.acquire():
            raise LockNotAcquired(
                f"无法获取锁: {self.key}"
            )
        return self

    # **exit** 方法：上下文管理器出口
    #### 方法整体作用

    # 退出 `with` 代码块时**自动释放锁**，无论代码正常执行结束还是抛出异常，都会执行释放逻辑，是「保证锁一定会释放」的关键设计。  
    def __exit__(
        self,

        # 三个参数是 Python 上下文管理器的标准参数：

        # - `exc_type`：异常类型，没有异常则为 None
        # - `exc`：异常对象，没有异常则为 None
        # - `tb`：异常回溯栈，没有异常则为 None
        exc_type:type[BaseException] | None,
        exc:BaseException | None,
        tb:TracebackType | None,
    )->None:
        # - 无条件调用释放方法，确保锁一定会被释放
        # - 即使业务代码抛出异常，`__exit__` 也会被执行，避免锁泄
        self.release()

## 整体设计总结

# 这是一套工业级的 Redis 分布式锁实现，覆盖了分布式锁的三大核心安全问题：

# 1. **防死锁**：SET 原子设置过期时间，客户端宕机也能自动释放
# 2. **防误删**：UUID 令牌 + Lua 原子校验，只能释放自己的锁
# 3. **防泄漏**：上下文管理器自动释放，异常场景也能保证解锁

# 使用方式上有两种：

# - 手动调用：`lock.acquire()` → 业务逻辑 → `lock.release()`
# - 上下文管理器（推荐）：`with DistributedLock(...):` 自动加解锁，更安全