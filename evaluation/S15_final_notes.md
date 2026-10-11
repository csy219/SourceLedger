# S15 最终总结：Runtime 执行图、状态生命周期与失败路径

## 1. 阶段目标

S15 定义并验证 Agent Runtime 的执行边界：

- 上下文、工具、Run 和 Checkpoint 状态分离
- 执行图节点和路由
- 工具调用幂等
- 失败分类、重试和终止策略
- 状态转换规则
- Checkpoint 写入时机

## 2. 产物

- `runtime/S15_state_reference.py`
- `runtime/S15_graph_reference.py`
- `runtime/S15_failure_policy_reference.py`
- `runtime/S15_transition_reference.py`
- `runtime/S15_runtime_smoke.py`
- `evaluation/S15_runtime_state_design.md`

## 3. 状态模型

状态已拆分为：

- `ContextState`
- `ToolCallRecord`
- `RunState`
- `FailureDecision`
- `CheckpointPlan`

关键字段：

```text
run_id
thread_id
goal
status
current_node
step_count
max_steps
context
tool_calls
created_at
updated_at
```

工具调用记录：

```text
tool_call_id
tool_name
arguments
status
attempt
max_attempts
result
error
started_at
finished_at
```

## 4. 执行图

执行图覆盖：

```text
START
-> build_context
-> call_model
-> route
-> register_tool_call
-> permission_check
-> execute_tool
-> save_observation
-> save_checkpoint
-> call_model
-> finish
```

失败分支覆盖：

```text
非法模型输出
权限拒绝
工具超时
工具临时错误
重复工具调用
步骤超限
```

## 5. 失败策略

策略区分：

```text
retry_tool
retry_model
recall_model
repair_context
wait_approval
verify_side_effect
reuse_result
retry_checkpoint
terminate
```

重要边界：

- 模型超时可以重试。
- 工具超时且没有副作用可以重试。
- 工具可能已经产生副作用时不能直接重试，必须先核对状态。
- 权限拒绝不能自动重试。
- 重复 `tool_call_id` 直接复用已有结果。
- Checkpoint 写入失败不能继续执行有副作用的工具。

## 6. 状态转换与 Checkpoint

合法转换：

```text
pending -> running
running -> waiting_approval
waiting_approval -> running
running -> completed
running -> failed
running -> cancelled
failed -> running
```

非法转换会被拒绝：

```text
completed -> running
```

需要同步 Checkpoint 的事件：

```text
run_started
model_response_received
tool_call_registered
before_side_effect
after_side_effect
approval_required
final_answer
failure
```

## 7. Smoke Test 结果

场景全部通过：

```text
success_completed = true
success_executed_once = true
duplicate_executed_once = true
retry_executed_twice = true
permission_rejected = true
step_limit_failed = true
all_passed = true
```

关键结果：

```text
正常执行：工具执行 1 次，任务完成
重复调用：模型调用 3 次，工具执行 1 次
超时重试：工具执行 2 次，最终完成
权限拒绝：工具状态 rejected，任务失败
步骤超限：任务终止于 step_limit
```

## 8. 已知限制

- 当前 Checkpoint 仍然是内存实现，尚未接入 MySQL/PostgreSQL。
- 权限拒绝在 RuntimeGraph 中当前直接失败，FailurePolicy 中定义的是等待审批，后续需要统一。
- 还没有真实 LLM 和真实工具接入。
- 还没有跨进程恢复测试。
- 还没有生产级锁、幂等键和分布式调度。

## 9. 下一阶段

S16 将把内存状态升级为 MySQL/PostgreSQL：

- 会话、任务、工具调用和 Runtime 状态持久化
- 可恢复 Checkpointer
- 跨进程恢复
- 事务、索引、checkpoint 粒度和迁移方案


<!-- S15 还没有真正接入生产数据库，所以当前 Checkpoint 还是内存实现。这个限制要明确写进总结。 -->
