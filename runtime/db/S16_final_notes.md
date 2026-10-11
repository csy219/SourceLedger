S16 总结

S16 解决的是：
Agent Runtime 的持久化、幂等和跨进程恢复
前面的 Runtime 状态只存内存。进程一退出，任务、工具调用、Checkpoint 全部丢失。S16 把这些状态迁移到 PostgreSQL。

1. 数据库基础设施
已建立：
PostgreSQL Docker 容器
.env 数据库配置
SQLAlchemy Engine
Session Factory
Alembic 迁移
连接结果：
database_connection=1
数据库表：
runs
checkpoints
tool_calls
idempotency_keys
alembic_version


2. 四张核心表
runs
保存一次 Run 的当前摘要：
run_id、thread_id、goal、status、
current_node、step_count、max_steps
checkpoints
保存完整 RunState 快照：
run_id、version、node、state_snapshot、created_at
tool_calls
保存工具调用状态：
tool_call_id、参数、attempt、
status、result、error、时间
idempotency_keys
保存幂等操作：
key、run_id、status、result、error


3. Repository 层
已实现：
RunStateRepository
ToolCallRepository
IdempotencyRepository
用途分别是：
RunStateRepository：
创建、读取、更新和查询 Run

ToolCallRepository：
幂等创建工具调用、更新 running/succeeded/failed

IdempotencyRepository：
首次请求执行，重复请求复用结果


4. Checkpointer
已实现：
state_to_dict
state_from_dict
DatabaseCheckpointer.save
DatabaseCheckpointer.load_latest
DatabaseCheckpointer.load_version
DatabaseCheckpointer.list_versions
每次保存 Checkpoint：
锁定对应 Run
计算 next_version
写入完整状态快照
同一事务更新 runs 当前状态
Checkpoint 测试结果：
first_version=1
second_version=2
versions=[1, 2]
loaded_status=running
loaded_node=call_model
loaded_step_count=1
loaded_tool_status=succeeded


5. 跨进程恢复
已准备：
S16_6_recovery_writer.py
S16_6_recovery_reader.py
S16_6_cross_process_smoke.py
本质是：
进程 A 创建 Run 并写 Checkpoint
进程 A 退出
进程 B 从 PostgreSQL 读取最新 Checkpoint
恢复 RunState
如果测试成功，应得到：
writer_pid != reader_pid
recovery_ok=true
这证明恢复来自数据库，不是内存对象。


6. S16 的核心收益
任务状态可以持久化
工具调用可以持久化
相同 tool_call_id 不会重复创建
重复请求可以复用幂等结果
Checkpoint 有递增版本
进程退出后可以恢复任务
Checkpoint 和 Run 当前状态在同一事务更新


7. 当前限制
目前只验证 PostgreSQL，尚未验证 MySQL
使用同步 SQLAlchemy，还没有异步数据库访问
还没有分布式任务租约和 worker 锁
还没有 Redis
还没有连接池参数调优
还没有 Checkpoint 清理和保留策略
还没有接入 FastAPI
