import json
import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from redis import Redis

from runtime.resilience.S17_4_distributed_lock import (
    DistributedLock,
)
from runtime.resilience.S17_4_rate_limiter import (
    LocalRateLimiter,
    RedisRateLimiter,
)

def main()->int:
    # 1. 测试准备：生成唯一测试键
    # - `key`：随机生成的十六进制唯一字符串
    # - 作用：本次测试所有 Redis key 都基于这个值拼接，保证每次运行测试用的都是全新的 key，不会被上一次测试的残留数据影响，确保测试结果准确
    key=uuid.uuid4().hex

    # 2. 第一部分：本地限流器功能验证
    # - `local = LocalRateLimiter()`：创建本地限流器实例
    # - `local_results`：存储 3 次限流检查的结果（只取 `allowed` 布尔值）
    # - 测试逻辑：同一个限流 key，限制 60 秒内最多 2 次请求，连续调用 3 次
    # - 第 1、2 次：窗口内请求数未超阈值，返回 `True`（放行）
    # - 第 3 次：达到阈值，返回 `False`（限流）
    # - 预期结果：`[True, True, False]`，验证本地滑动窗口限流逻辑正确
    local=LocalRateLimiter()
    local_results=[
        local.check(
            key=f"local:{key}",
            limit=2,
            window_seconds=60,
        ).allowed
        for _ in range(3)
    ]

    # 3. 第二部分：Redis 连接初始化
    # `redis_url`：Redis 连接地址
    # - 优先从环境变量读取，没有就用默认值 `redis://localhost:6380/0`
    # - 对应你之前 `.env` 里配置的 `REDIS_URL`
    redis_url=os.getenv(
        "REDIS_URL",
        "redis://localhost:6380/0",
    )

    # `client = Redis.from_url(...)`：通过 URL 创建 Redis 客户端实例
    # - `decode_responses=True`：自动把 Redis 返回的 bytes 结果解码成字符串，不用手动转码
    client=Redis.from_url(
        redis_url,
        decode_responses=True,
    )

    # `client.ping()`：向 Redis 发送 ping 命令
    # - 作用：连通性检查，确保 Redis 连接正常再继续测试；如果连不上直接抛异常，避免后续测试全部失败
    client.ping()

    # 4. 第三部分：Redis 限流器功能验证
    # - `limiter = RedisRateLimiter(client)`：创建 Redis 限流器实例，传入 Redis 客户端
    # - `redis_key = f"rate:{key}"`：Redis 限流 key，加 `rate:` 前缀做命名空间区分
    # - `redis_results`：存储 3 次 Redis 限流检查的结果
    # - 测试逻辑：和本地版完全一致，60 秒限制 2 次，连续调用 3 次
    # - 预期结果：`[True, True, False]`，验证 Redis 版滑动窗口限流逻辑、Lua 原子脚本都正常工作
    limiter=RedisRateLimiter(client)
    redis_key=f"rate:{key}"
    redis_results=[
        limiter.check(
            key=redis_key,
            limit=2,
            window_seconds=60,
        ).allowed
        for _ in range(3)
    ]


    # 5. 第四部分：分布式锁互斥与释放验证
    # - `lock_key = f"lock:{key}"`：锁的 Redis key，加 `lock:` 前缀区分
    # - `first_lock`、`second_lock`：两个独立的分布式锁实例
    # - 作用：模拟**两个不同的客户端 / 服务实例**，竞争同一把锁，验证互斥性
    # - 两个锁用完全相同的 key 和 ttl，模拟真实的分布式竞争场景
    # - `ttl_ms=500`：锁 500 毫秒后自动过期，测试用短过期即可
    lock_key = f"lock:{key}"
    first_lock = DistributedLock(
        client=client,
        key=lock_key,
        ttl_ms=500,
    )
    second_lock = DistributedLock(
        client=client,
        key=lock_key,
        ttl_ms=500,
    )

    # 锁测试第一步：验证互斥性
    # - `first_acquired`：第一个锁尝试获取，预期 `True`（锁没人占用，成功获取）
    # - `second_acquired`：第二个锁在第一个锁持有期间尝试获取，预期 `False`（锁已被占用，互斥生效）
    # - 核心验证点：同一时间只有一个实例能拿到锁，互斥特性正常
    first_acquired = first_lock.acquire()
    second_acquired = second_lock.acquire()

    # 锁测试第二步：验证释放与重入
    first_released=first_lock.release()
    second_acquired_after_release=second_lock.acquire()
    second_lock.release()

    output = {
        "local_rate_limit": local_results,
        "redis_rate_limit": redis_results,
        "first_lock_acquired": first_acquired,
        "second_lock_acquired_while_held": (
            second_acquired
        ),
        "first_lock_released": first_released,
        "second_lock_acquired_after_release": (
            second_acquired_after_release
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

if __name__ =="__main__":
    raise SystemExit(main())