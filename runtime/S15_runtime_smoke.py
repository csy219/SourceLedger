# 这段代码是**基于前文 Agent 编排引擎的自动化测试套件**。它通过实现可脚本化的钩子 `ScriptedHooks`，预设模型决策序列来模拟不同业务场景，
# 批量验证引擎的**正常流程、幂等复用、超时重试、权限拦截、步数限制**五大核心特性，内置自动断言校验，本质是一套面向运行时引擎的集成测试用例集。
# 整套测试完全基于之前定义的 `RuntimeGraph` 引擎和 `RunState` 状态模型，不侵入核心代码，属于黑盒测试。

import json
from dataclasses import dataclass,field
from typing import Any

from runtime.S15_graph_reference import (
    ModelDecision,
    RuntimeGraph,
)
from runtime.S15_state_reference import (
    RunState,
    RunStatus,
    ToolCallStatus,
)

@dataclass
class ScriptedHooks:
    decision:list[ModelDecision]
    permission_allowed:bool=True
    timeout_times:int=0
    model_calls: int=0
    tool_execute_count:int=0
    observations:list[dict[str,Any]]=field(
        default_factory=list
    )
    checkpoints:list[str]=field(
        default_factory=list
    )

    # 首次构建上下文时，将任务目标作为用户消息写入对话列表，和业务实现逻辑一致。
    def build_context(self,state:RunState)->None:
        if not state.context.messages:
            state.context.messages.append({"role":"user","content":state.goal})

    # call_model（脚本化核心）
    #     按顺序从预设决策列表中返回结果：
    # - 调用次数在列表长度内：按顺序返回预设决策
    # - 超出列表长度：返回兜底的最终回答，避免死循环
    # - 每次调用自动计数
    # > 设计价值：用数据驱动的方式模拟模型输出，无需真实调用大模型即可测试全流程逻辑。
    def call_model(self,state:RunState)->ModelDecision:
        if self.model_calls<len(self.decision):
            decision=self.decision[self.model_calls]
        else:
            decision=ModelDecision(kind="final",content="fallback final")
        self.model_calls+=1
        return decision

    # 直接返回全局权限开关，用于快速模拟权限通过 / 拒绝两种场景。
    def check_permission(self,state:RunState,decision:ModelDecision)->bool:
        return self.permission_allowed
    

    # execute_tool（超时模拟核心）
    # - 执行计数 +1
    # - 前 `timeout_times` 次执行强制抛出超时异常，精准模拟「前 N 次失败、之后成功」的重试场景
    # - 成功则返回包含执行次数的结果，便于验证执行次数
    def execute_tool(self,state:RunState,decision:ModelDecision)->Any:
        self.tool_execute_count+=1
        if self.tool_execute_count <= self.timeout_times:
            raise TimeoutError("simulated timeout")
        return {"tool":decision.tool_name,"executed_count":self.tool_execute_count}

    # 记录观测结果，并将工具返回写入上下文消息，和业务逻辑一致。
    def append_observation(self,state:RunState,tool_call_id:str,result:Any)->None:
        self.observations.append({"tool_call_id":tool_call_id,"result":result})
        state.context.messages.append(
            {
                "role":"tool",
                "tool_call_id":tool_call_id,
                "content":json.dumps(result,ensure_ascii=False,indent=2)
            }
        )


    # 记录检查点节点名称，用于统计和路径验证。
    def save_checkpoint(self,state:RunState,node:str)->None:
        self.checkpoints.append(node)

# 3. 工具函数 `tool_call`
# 快速生成工具调用类型的决策对象，简化测试用例编写，避免重复构造代码。
def tool_call(tool_call_id)->ModelDecision:
    return ModelDecision(
        kind="tool_call",
        tool_call_id=tool_call_id,
        tool_name="shell.run",
        arguments={"command":"pytest -q"}
    )


# 4. 场景运行器 `run_scenario`
# 通用测试场景执行函数，封装重复的初始化、运行、结果提取逻辑
# 执行流程：
# 1. 创建任务状态：线程 ID、目标均使用场景名，配置最大步数
# 2. 实例化 `ScriptedHooks`，传入场景参数
# 3. 创建编排引擎并运行
# 4. 提取所有工具调用的最终状态
# 5. 组装标准化结果返回，包含：场景名、最终状态、当前节点、步数、模型调用次数、工具执行次数、工具状态字典、观测数量、检查点数量
# > 设计价值：统一测试用例的执行和输出格式，新增场景只需调用该函数即可，无需重复编写样板代码。
def run_scenario(
        name:str,
        decisions:list[ModelDecision],
        max_steps:int =5,
        permission_allowed:bool=True,
        timeout_times:int=0,
)->dict[str,Any]:
    state=RunState.create(
        thread_id=f"thread-{name}",
        goal=f"scenario {name}",
        max_steps=max_steps,
    )
    hooks=ScriptedHooks(
        decision=decisions,
        permission_allowed=permission_allowed,
        timeout_times=timeout_times,
    )
    graph=RuntimeGraph(hooks)
    result=graph.run(state)

    tool_call_states={
        call_id:record.status.value
        for call_id,record
        in result.tool_calls.items()
    }
    return {
        "name": name,
        "status": result.status.value,
        "current_node": result.current_node,
        "step_count": result.step_count,
        "model_calls": hooks.model_calls,
        "tool_execute_count": (
            hooks.tool_execute_count
        ),
        "tool_call_states": tool_call_states,
        "observation_count": len(
            hooks.observations
        ),
        "checkpoint_count": len(
            hooks.checkpoints
        ),
    }

def main() -> int:
    # 5. 主函数：5 个测试场景
    scenarios = [
        run_scenario(
            name="success",
            decisions=[
                tool_call("call-success"),
                ModelDecision(
                    kind="final",
                    content="done",
                ),
            ],
        ),
        run_scenario(
            name="duplicate",
            decisions=[
                tool_call("call-duplicate"),
                tool_call("call-duplicate"),
                ModelDecision(
                    kind="final",
                    content="done",
                ),
            ],
        ),
        run_scenario(
            name="timeout_retry",
            decisions=[
                tool_call("call-timeout"),
                tool_call("call-timeout"),
                ModelDecision(
                    kind="final",
                    content="done",
                ),
            ],
            timeout_times=1,
        ),
        run_scenario(
            name="permission_denied",
            decisions=[
                tool_call("call-permission"),
            ],
            permission_allowed=False,
        ),
        run_scenario(
            name="step_limit",
            decisions=[
                tool_call("call-step-1"),
                tool_call("call-step-2"),
                tool_call("call-step-3"),
            ],
            max_steps=2,
        ),
    ]
    # 6. 断言校验
    # 6 条断言对应 5 个场景的核心预期，逐条验证引擎逻辑是否正确：
    #      断言项	          验证目标
    # success_completed	正常流程任务能成功完成
    # success_executed_once	正常流程工具只执行一次
    # duplicate_executed_once	相同 ID 重复调用时幂等生效，工具不重复执行
    # retry_executed_twice	超时后重试机制生效，工具执行 2 次
    # permission_rejected	权限拒绝时任务失败，工具标记为已拒绝
    # step_limit_failed	达到最大步数后任务终止，节点正确
    assertions = {
        "success_completed": scenarios[0]["status"] == "completed",
        "success_executed_once": scenarios[0]["tool_execute_count"] == 1,
        "duplicate_executed_once": scenarios[1]["tool_execute_count"] == 1,
        "retry_executed_twice": scenarios[2]["tool_execute_count"] == 2,
        "permission_rejected": (
            scenarios[3]["status"] == "failed"
            and scenarios[3]["tool_call_states"].get("call-permission") == ToolCallStatus.REJECTED.value
        ),
        "step_limit_failed": (
            scenarios[4]["status"] == "failed"
            and scenarios[4]["current_node"] == "step_limit"
        ),
    }
    output = {
        "scenarios": scenarios,
        "assertions": assertions,
        "all_passed": all(assertions.values()),
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not output["all_passed"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())





    
