# 这段代码在前一节状态数据结构的基础上，实现了一个**生产级 Agent 工作流编排引擎**。核心采用「状态机 + 钩子协议」的架构：
# `RuntimeGraph` 固化通用流程控制逻辑，`RuntimeHooks` 协议定义业务扩展点，
# 将流程控制与业务实现完全解耦，天然支持检查点持久化、故障重试、幂等执行、权限校验、人工审批等核心能力。

import json
from dataclasses import dataclass,field

# `Protocol` 是核心：用于定义钩子接口契约，实现鸭子类型的抽象 —— 
# 只要类实现了协议定义的方法，就被视为符合协议，无需显式继承，符合 Python 惯用的解耦设计
from typing import Any,Protocol
from runtime.S15_state_reference import(
    FailureKind,
    RunState,
    RunStatus,
    ToolCallStatus,
    decide_failure,
)

# 模型决策统一输出结构
@dataclass
class ModelDecision:
    kind:str
    content:str=""
    tool_call_id:str=""
    tool_name:str=""
    arguments:dict[str,Any]=field(default_factory=dict)
    requires_approval:bool=False


# 运行时钩子协议（扩展点定义）
# 钩子方法	职责
# build_context	构建模型输入上下文，比如拼接历史消息、注入检索结果、压缩摘要等
# call_model	调用大模型，接收当前状态，返回标准化决策
# check_permission	工具调用前的权限校验，判断当前工具是否允许执行
# execute_tool	实际执行工具逻辑，返回工具执行结果
# append_observation	将工具执行结果追加到上下文中，供下一轮模型调用使用
# save_checkpoint	持久化当前状态到存储（数据库 / 磁盘），用于故障恢复
class RuntimeHooks(Protocol):
    def build_context(
        self,
        state:RunState,
    )->None:
        ...
    def call_model(
        self,
        state:RunState,
    )->ModelDecision:
        ...
    def check_permission(
        self,
        state:RunState,
        decision:ModelDecision
    )->bool:
        ...
    def execute_tool(
        self,
        state:RunState,
        decision:ModelDecision,
    )->Any:
        ...
    def append_observation(
        self,
        state:RunState,
        tool_call_id:str,
        result:Any,
    )->None:
        ...
    def save_checkpoint(
        self,
        state:RunState,
        node:str,
    )->None:
        ...

# 核心工作流引擎 RuntimeGraph
# 构造函数接收符合 `RuntimeHooks` 协议的实现，将钩子注入引擎。
class RuntimeGraph:
    def __init__(
        self,
        hooks:RuntimeHooks,
    )->None:
        self.hooks=hooks

    ##### 核心 run 方法（状态机主循环）
    # 这是整个引擎的核心，完整实现了 Agent 「上下文构建 → 模型决策 → 工具执行 → 结果回填」的闭环，
    # 下面按执行顺序拆解：
    def run(
        self,
        state:RunState,
    )->RunState:
        # - **流程启动**：将任务状态置为运行中，起始节点设为 `start`
        # - **入口检查点**：启动前先持久化一次状态，保证故障后可以从起点恢复
        state.status=RunStatus.RUNNING
        state.current_node="start"
        self.hooks.save_checkpoint(state,state.current_node)

        # - **主循环条件**：`state.can_continue()` 即「运行中 + 未超最大步数」，内置死循环防护
        # - **节点 1：构建上下文**：调用钩子构建模型输入，完成后保存检查点
        while state.can_continue():
            state.current_node="build__context"
            self.hooks.build_context(state)
            self.hooks.save_checkpoint(state,state.current_node)

            #  - **节点 2：模型决策**：调用大模型得到决策
            # - **分支 1：最终回答**：任务完成，状态置为已完成，追加助手回复，保存检查点后直接返回
            # - **分支 2：无效输出**：模型返回了未知类型，任务失败，记录节点后返回
            state.current_node="call_model"
            decision=self.hooks.call_model(state)

            if decision.kind=="final":
                state.status=RunStatus.COMPLETED
                state.current_node="finish"
                state.context.messages.append(
                    {
                        "role":"assistant","content":decision.content
                    }
                )
                self.hooks.save_checkpoint(state,state.current_node)
                return state

            if decision.kind !="tool_call":
                state.status=RunStatus.FAILED
                state.current_node="invalid_model_output"
                self.hooks.save_checkpoint(state,state.current_node)
                return state
            

            # **幂等注册与重复调用处理**：
            # 1. 尝试注册工具调用，返回是否为首次注册
            # 2. 重复注册时：
            # - 若已有记录执行成功：直接复用结果，步数 + 1，进入下一轮循环（**不重复执行工具**，幂等核心）
            # - 若已有记录不可重试：任务失败，阻断重复执行
            registered=state.register_tool_call(
                tool_call_id=decision.tool_call_id,
                tool_name=decision.tool_name,
                arguments=decision.arguments,
            )

            if not registered:
                existing=state.tool_calls[decision.tool_call_id]
                if existing.status == ToolCallStatus.SUCCEEDED:
                    state.current_node="reuse_tool_result"
                    state.increment_step()
                    self.hooks.save_checkpoint(state,state.current_node)
                    continue
                if not existing.can_retry():
                    state.status=RunStatus.FAILED
                    state.current_node="duplicate_tool_call_blocked"
                    self.hooks.save_checkpoint(state,state.current_node)
                    return state
            # **工审批节点**：如果工具需要审批，任务状态置为「待审批」，保存检查点后暂停返回，等待人工触发继续执行
            if decision.requires_approval:
                state.status=RunStatus.WAITING_APPROVAL
                state.current_node="waiting_approval"
                self.hooks.save_checkpoint(state,state.current_node)
                return state

            #   - **节点 3：权限校验**：调用权限钩子
            #   - 校验不通过：标记工具调用为「被拒绝」，任务失败，记录节点后返回

            state.current_node="permission_check"
            allowed=self.hooks.check_permission(state,decision)

            if not allowed:
                state.mark_tool_failed(
                    tool_call_id=decision.tool_call_id,
                    status=ToolCallStatus.REJECTED,
                    error="permission_denied"
                )
                state.status=RunStatus.FAILED
                state.current_node="permission_denied"
                self.hooks.save_checkpoint(state,state.current_node)
                return state

            # **节点 4：工具执行 - 超时异常分支**：
            # 1. 先标记工具为运行中
            # 2. 捕获超时异常：标记工具超时，调用失败决策引擎判断是否可重试
            # 3. 步数 + 1，保存检查点
            # 4. 若为终止错误或重试次数耗尽：任务失败；否则进入下一轮循环重试

            state.current_node="execute_tool"
            state.mark_tool_running(decision.tool_call_id)
            try:
                result=self.hooks.execute_tool(state,decision)
            except TimeoutError:
                record=state.mark_tool_failed(
                    tool_call_id=decision.tool_call_id,
                    status=ToolCallStatus.TIMED_OUT,
                    error="tool_timeout",
                )
                failure=decide_failure(FailureKind.TOOL_TIMEOUT)
                state.current_node="tool_timeout" if failure.retryable else "tool_failed"
                state.increment_step()
                self.hooks.save_checkpoint(state,state.current_node)
                if failure.terminal or not record.can_retry():
                    state.status=RunStatus.FAILED
                    return state
                continue

            # **工具执行 - 通用异常分支**：
            # - 捕获其他所有异常，标记工具失败
            # - 判断是否可重试，不可重试则任务失败，否则继续重试
            except Exception as exc:
                record=state.mark_tool_failed(
                    tool_call_id=decision.tool_call_id,
                    status=ToolCallStatus.FAILED,
                    error=str(exc)
                )
                state.current_node="tool_failed"
                state.increment_step()
                self.hooks.save_checkpoint(state,state.current_node)
                if not record.can_retry():
                    state.status=RunStatus.FAILED
                    return state
                continue

            # **工具执行成功分支**：
            # 1. 标记工具执行成功，存储结果
            # 2. 调用钩子将工具结果回填到上下文
            # 3. 步数 + 1，保存检查点，进入下一轮循环

            state.mark_tool_succeeded(tool_call_id=decision.tool_call_id,result=result)
            self.hooks.append_observation(
                state=state,
                tool_call_id=decision.tool_call_id,
                result=result,
            )
            state.current_node="save_observation"
            state.increment_step()
            self.hooks.save_checkpoint(state,state.current_node)

        # - **循环退出（步数超限）**：达到最大步数仍未结束，任务失败，记录「步数超限」节点后返回
        # > 1. **每节点必存检查点**：任何状态变更后都持久化，故障恢复后可以精确到节点继续执行
        # > 2. **原生幂等**：相同 tool_call_id 自动复用结果，杜绝重复执行副作用
        # > 3. **分级异常处理**：超时与普通异常分开处理，结合失败决策引擎自动判断重试策略
        # > 4. **内置安全护栏**：最大步数限制、权限校验、审批拦截三层防护
        state.status = RunStatus.FAILED
        state.current_node = "step_limit"
        self.hooks.save_checkpoint(state, state.current_node)
        return state

class DemoHooks:
    def __init__(self) -> None:
        self.model_calls = 0
        self.tool_execute_count = 0
        self.checkpoints: list[str] = []
        self.observations: list[dict[str, Any]] = []

    def build_context(
        self,
        state: RunState,
    ) -> None:
        if not state.context.messages:
            state.context.messages.append(
                {
                    "role": "user",
                    "content": state.goal,
                }
            )

    def call_model(
        self,
        state: RunState,
    ) -> ModelDecision:
        self.model_calls += 1

        if self.model_calls == 1:
            return ModelDecision(
                kind="tool_call",
                tool_call_id="call-1",
                tool_name="shell.run",
                arguments={"command": "pytest -q"},
            )

        if self.model_calls == 2:
            return ModelDecision(
                kind="tool_call",
                tool_call_id="call-1",
                tool_name="shell.run",
                arguments={"command": "pytest -q"},
            )

        return ModelDecision(
            kind="final",
            content="测试已经通过。",
        )

    def check_permission(
        self,
        state: RunState,
        decision: ModelDecision,
    ) -> bool:
        return decision.tool_name == "shell.run"

    def execute_tool(
        self,
        state: RunState,
        decision: ModelDecision,
    ) -> Any:
        self.tool_execute_count += 1
        return {
            "exit_code": 0,
            "stdout": "2 passed",
        }

    def append_observation(
        self,
        state: RunState,
        tool_call_id: str,
        result: Any,
    ) -> None:
        observation = {
            "tool_call_id": tool_call_id,
            "result": result,
        }
        self.observations.append(observation)
        state.context.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(
                    result,
                    ensure_ascii=False,
                ),
            }
        )

    def save_checkpoint(
        self,
        state: RunState,
        node: str,
    ) -> None:
        self.checkpoints.append(node)


def main() -> int:
    state = RunState.create(
        thread_id="thread-1",
        goal="检查仓库并修复 CI 失败",
    )
    hooks = DemoHooks()
    graph = RuntimeGraph(hooks)
    result = graph.run(state)

    payload = {
        "status": result.status.value,
        "current_node": result.current_node,
        "step_count": result.step_count,
        "model_calls": hooks.model_calls,
        "tool_execute_count": (
            hooks.tool_execute_count
        ),
        "checkpoints": hooks.checkpoints,
        "observations": hooks.observations,
        "tool_call": result.tool_calls[
            "call-1"
        ].to_dict(),
        "messages": result.context.messages,
    }

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





