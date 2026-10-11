S17 总结：


S17 解决的是 Runtime 的容错和重复执行问题：
超时怎么办？
失败后重试几次？
重试间隔多久？
主方案失败后降级到什么？
下游持续故障时如何熔断？
如何限制请求频率？
多实例如何互斥执行？
重复请求和重复工具调用如何只执行一次？


1. 策略配置
已建立：
runtime/resilience/models.py
runtime/resilience/config.py
configs/resilience.json
定义了：
TimeoutPolicy
RetryPolicy
FallbackPolicy
RateLimitPolicy
IdempotencyPolicy
OperationPolicy
ResilienceConfig
当前策略包含：
model
retrieval
tool
redis
webhook
每种操作独立配置：
timeout_ms
max_attempts
base_delay_ms
max_delay_ms
jitter_ratio
fallback_chain
rate_limit
idempotency


2. Timeout、retry 和 backoff
实现文件：
runtime/resilience/S17_2_executor.py
核心入口：
execute_with_policy(...)
它实现了：
同步函数超时控制
临时错误重试
指数退避
随机 jitter
重试耗尽
不可重试错误立即终止
异常语义：
OperationTimeout              单次调用超时
RetryExhausted                重试耗尽
NonRetryableOperationError    不可重试错误


3. Fallback 和熔断器
实现文件：
runtime/resilience/S17_3_fallback.py
runtime/resilience/S17_3_circuit_breaker.py
Fallback：
primary 失败
-> 按 fallback_chain 依次尝试
-> 成功返回实际来源
-> 全部失败抛 FallbackExhausted
熔断器状态：
CLOSED    正常放行
OPEN      拒绝调用，避免继续打下游
HALF_OPEN 恢复期试探
连续失败达到阈值后进入 OPEN。恢复时间到后进入 HALF_OPEN。探测成功恢复 CLOSED，失败重新进入 OPEN。


4. 限流和分布式锁
实现文件：
runtime/resilience/S17_4_rate_limiter.py
runtime/resilience/S17_4_distributed_lock.py
限流器：
LocalRateLimiter
RedisRateLimiter
本地限流适合单进程；Redis 限流适合多实例全局限流。
Redis 限流使用：
Sorted Set
ZREMRANGEBYSCORE
ZCARD
ZADD
PEXPIRE
Lua 原子脚本
分布式锁使用：
SET key token NX PX ttl_ms
释放锁时通过 Lua 比较 token，确保只能释放自己持有的锁。


5. 请求级和工具级幂等
实现文件：
runtime/resilience/S17_5_idempotency.py
请求级幂等：
相同 request key
-> 已经成功则返回历史结果
-> 正在执行则抛 RequestInProgress
-> 已失败则默认拒绝，必要时可显式重试
工具级幂等：
run_id + tool_call_id
-> 已成功则直接复用结果
-> PENDING/RUNNING 则拒绝重复执行
-> 重试次数耗尽则抛 ToolRetryExhausted
核心保证：
同一个工具调用只会真正执行一次


6. 故障注入结果
实现文件：
runtime/resilience/S17_6_fault_injection_smoke.py
实际报告：
project_a/evaluation/reports/S17_6_fault_injection.json
结果：
scenarios=4
passed=4
failed=0
all_passed=true
四个场景：
timeout_retry_backoff        passed=true
fallback_circuit_breaker     passed=true
rate_limit_distributed_lock  passed=true
request_tool_idempotency     passed=true
关键验证结果：
超时、重试、退避正常
重试耗尽和不可重试错误可区分
fallback 降级正常
熔断 OPEN 和 HALF_OPEN 恢复正常
本地限流和 Redis 限流正常
分布式锁互斥和释放正常
request_call_count=1
tool_call_count=1


7. S17 的核心价值
失败不再直接崩溃
临时错误可以恢复
持续错误可以熔断
主链路失败可以降级
多实例可以全局限流
敏感操作可以加分布式锁
重复请求不会重复写数据
重复工具调用不会重复执行副作用


8. 已知限制
线程池超时不能强制终止底层业务线程
Redis 锁目前没有自动续租
限流目前是滑动窗口，不是令牌桶
没有接入死信队列
没有接入 OTel 和告警
没有对所有真实模型和工具做端到端故障注入