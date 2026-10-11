# 这段代码是一套**领域对象序列化 / 反序列化工具集**，
# 是整个 Agent 运行时状态流转的基础组件。它的核心作用是在「内存中的强类型业务对象」和「字典 / JSON 格式」之间做双向转换，
# 让状态可以被存入数据库、写入缓存、在消息队列中传递，或者通过网络接口传输。

# 函数	方向	作用
# state_to_dict	对象 → 字典	把 RunState 完整序列化为字典，用于持久化、传输
# tool_call_from_dict	字典 → 对象	反序列化单条工具调用记录，是基础单元
# state_from_dict	字典 → 对象	反序列化完整运行状态，内部嵌套还原上下文和工具调用
# 它位于「业务领域层」和「外部基础设施层」之间：
# 业务逻辑 ↔ RunState/ToolCallRecord 对象 ↔ 本转换层 ↔ 字典/JSON ↔ 数据库/缓存/MQ/接口


from typing import Any

from runtime.S15_state_reference import (
    ContextState,
    RunState,
    RunStatus,
    ToolCallRecord,
    ToolCallStatus,
)


# 1. `state_to_dict`：状态序列化
# - 功能：将内存中的 `RunState` 对象转为普通字典。
# - 设计：不直接使用 `dataclasses.asdict`，而是调用对象自身的 `to_dict()` 方法，好处是可以自定义序列化规则：比如枚举自动转字符串、嵌套对象递归转换、屏蔽内部字段等，行为完全可控。

def state_to_dict(
    state: RunState,
) -> dict[str, Any]:
    return state.to_dict()

# 2. `tool_call_from_dict`：工具调用反序列化
def tool_call_from_dict(payload: dict[str, Any]) -> ToolCallRecord:
    return ToolCallRecord(
        tool_call_id=str(payload["tool_call_id"]),
        tool_name=str(payload["tool_name"]),
        arguments=payload.get("arguments") or {},
        status=ToolCallStatus(payload.get("status", "pending")),
        attempt=int(payload.get("attempt", 0)),
        max_attempts=int(payload.get("max_attempts", 3)),
        result=payload.get("result"),
        error=str(payload.get("error", "")),
        started_at=str(payload.get("started_at", "")),
        finished_at=str(payload.get("finished_at", "")),
    )

### 3. `state_from_dict`：完整运行状态反序列化
# 这是最核心的函数，完整还原两层嵌套结构：`ContextState` 上下文 + `tool_calls` 工具调用字典。
def state_from_dict(payload: dict[str, Any]) -> RunState:
    # 第一层：还原上下文对象
    context_payload = payload.get("context") or {}
    context = ContextState(
        messages=context_payload.get("messages", []),
        history_summary=str(context_payload.get("history_summary", "")),
        retrieval_context=context_payload.get("retrieval_context", []),
        citations=context_payload.get("citations", []),
        conflict=context_payload.get("conflict", {}),
        context_tokens=int(context_payload.get("context_tokens", 0)),
    )

    # 第二层：还原所有工具调用记录（字典结构，id 为 key）
    tool_calls = {
        call_id: tool_call_from_dict(tool_payload)
        for call_id, tool_payload in (payload.get("tool_calls") or {}).items()
    }

    # 构造主状态对象
    return RunState(
        run_id=str(payload["run_id"]),
        thread_id=str(payload["thread_id"]),
        goal=str(payload["goal"]),
        status=RunStatus(payload.get("status", "pending")),
        current_node=str(payload.get("current_node", "start")),
        step_count=int(payload.get("step_count", 0)),
        max_steps=int(payload.get("max_steps", 20)),
        context=context,
        tool_calls=tool_calls,
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )
## 三、为什么要专门写这一层？核心价值
### 1. 强类型与弱格式的解耦
# - 业务层全程使用强类型对象（`RunState`、枚举），有 IDE 补全、类型检查，避免字段名写错、类型不匹配的低级错误。
# - 数据库、缓存、消息队列、HTTP 接口只能处理字典 / JSON，需要这一层做桥接。
# ### 2. 转换逻辑集中，维护成本低
# 所有序列化规则集中在这几个函数里，后续加字段、改格式、做兼容，只需要改一处，不用在业务代码里到处写字典取值。
# ### 3. 向前兼容，平滑升级
# 因为所有非核心字段都有默认值，新版本新增字段后，旧版本存储的数据依然能正常加载；旧版本读取新版本数据也不会直接崩溃，非常适合长期迭代的系统。
# ### 4. 入口处数据校验
# 枚举类型的构造自带合法性校验，非法状态、非法枚举值在反序列化阶段就会被拦截，不会流入业务逻辑引发更隐蔽的问题。


## 四、和之前仓储层的关系

# 你之前看到的 `RunStateRepository`、`ToolCallRepository` 是**结构化持久化**—— 把核心字段拆成数据库列，方便按条件查询、排序、筛选。

# 而这套序列化对应的是**全状态持久化**—— 把整个 `RunState` 完整转成 JSON，存入数据库的 JSON 字段，或者 Redis、消息队列中。

# 两者通常配合使用：

# - 结构化字段：用于列表查询、状态筛选、统计报表
# - JSON 全状态：用于任务恢复、断点续跑、状态完整还原

# 比如任务中断后重启，就是从数据库读出 JSON 状态，调用 `state_from_dict` 还原成内存对象，然后从断点继续执行。


## 五、典型应用场景

# 1. **数据库持久化**：将运行状态序列化为 JSON 存入表的 `state` 字段，重启时反序列化恢复。
# 2. **消息队列**：把任务状态序列化后发到 MQ，消费者收到后反序列化继续执行。
# 3. **缓存**：热点状态序列化后存入 Redis，减少数据库查询。
# 4. **API 接口**：接口返回状态时，先转字典再序列化为 JSON 响应。
# 5. **调试与日志**：异常时打印完整状态字典，方便排查问题。