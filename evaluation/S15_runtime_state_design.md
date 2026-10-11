1. Runtime 执行图
需要画清楚：
START
  |
  v
加载 Run 状态
  |
  v
组装 Context
  |
  v
调用模型
  |
  v
模型返回最终回答？
  |是                    |否
  v                      v
写入最终状态          解析工具调用
  |                      |
  v                      v
END                 权限和 Schema 校验
                         |
                         v
                    执行工具
                         |
                         v
                    保存 Observation
                         |
                         v
                    写 Checkpoint
                         |
                         +--------> 回到组装 Context
图里必须标出：
模型调用
工具调用
权限检查
状态持久化
恢复点
失败分支
人工审批点


2. 状态模型
至少区分五类状态：
ContextState
ToolCallState
AgentState
RunState
CheckpointState
ContextState：
messages
history_summary
retrieval_context
citations
context_tokens
conflict
ToolCallState：
tool_call_id
tool_name
arguments
status
attempt
timeout_ms
result
error
started_at
finished_at
AgentState：
goal
plan
current_step
next_action
step_count
max_steps
status
RunState：
run_id
thread_id
status
current_node
created_at
updated_at
lease_owner
lease_expires_at
retry_count
CheckpointState：
checkpoint_id
run_id
version
state_snapshot
created_at
重点是：
上下文状态
工具状态
Agent 状态
调度状态
持久化状态
不能混成一个字典里随便改。


3. 正常流程和失败路径
正常流程：
用户请求
-> 加载状态
-> 组装上下文
-> 调用模型
-> 模型请求工具
-> 权限检查
-> 执行工具
-> 保存结果
-> 写 Checkpoint
-> 再次调用模型
-> 输出最终答案
必须列出的失败路径：
模型超时
模型返回格式错误
工具超时
工具权限拒绝
工具临时错误
工具业务错误
工具未知
重复工具调用
重复 Webhook
Checkpoint 写入失败
进程在中途崩溃
用户取消任务
重试次数耗尽
人工审批超时


4. 必须标出的风险点
要明确回答：
哪些操作可以安全重试？
哪些操作必须幂等？
哪些操作执行后不能恢复？
checkpoint 应该在哪一步写入？
工具已经执行但 checkpoint 还没写入时怎么办？
同一个 tool_call_id 重复出现时怎么办？
进程崩溃后如何判断工具是否已经执行？
S15 完成标准
执行图画出来
状态模型定义出来
正常流程和失败流程区分出来
不可恢复点标出来
重复执行风险标出来
Runtime 可复用边界标出来
能说明哪些状态放在内存、数据库、Redis 或工具系统