# Agent 执行过程中，到底有哪些状态？
# 哪些状态属于上下文？
# 哪些状态属于工具调用？
# 哪些状态属于整个任务？
# 失败以后如何判断能不能重试？
# 重复 tool_call_id 如何避免重复执行？
# 状态如何转成 JSON 保存？

import json
from dataclasses import dataclass,field
from datetime import datetime,timezone
from enum import Enum
from typing import Any
from uuid import uuid4


# json       把状态输出成 JSON
# dataclass  自动生成 __init__、__repr__ 等
# field      处理 list 和 dict 的可变默认值
# datetime   生成创建时间和更新时间
# timezone   使用 UTC 时间
# Enum       定义有限状态
# Any        允许工具结果或参数是任意类型
# uuid4      生成唯一 run_id


# 生成统一格式的 UTC 时间字符串
# 例如:2026-09-28T12:01:34.938044+00:00
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 工具状态必须和 Run 状态分开。
# 原因：
# 一个任务可以执行多个工具，
# 每个工具都有自己的 attempt、错误和结果。



# 它表示整个任务的运行状态：
# 继承 str 是为了：
# RunStatus.RUNNING.value
# 可以直接得到字符串：
# running
class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 它表示单个工具调用的状态：
# pending    已注册，未执行
# running    正在执行
# succeeded  成功
# failed     业务失败
# timed_out  超时
# rejected   权限拒绝
class ToolCallStatus(str,Enum):
    PENDING="pending"
    RUNNING="running"
    SUCCEEDED="succeeded"
    FAILED="failed"
    TIMED_OUT="timed_out"
    REJECTED="rejected"

class FailureKind(str, Enum):
    MODEL_TIMEOUT = "model_timeout"
    MODEL_FORMAT_ERROR = "model_format_error"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_TEMPORARY_ERROR = "tool_temporary_error"
    TOOL_BUSINESS_ERROR = "tool_business_error"
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    TOOL_UNKNOWN = "tool_unknown"
    DUPLICATE_TOOL_CALL = "duplicate_tool_call"
    CHECKPOINT_WRITE_ERROR = "checkpoint_write_error"
    USER_CANCELLED = "user_cancelled"
    APPROVAL_TIMEOUT = "approval_timeout"
    RETRY_EXHAUSTED = "retry_exhausted"



# retryable            是否可以重试
# checkpoint_required  处理前是否要保存状态
# terminal             是否必须终止
# reason               原因说明
@dataclass
class FailureDecision:
    retryable:bool
    checkpoint_required:bool
    terminal:bool
    reason:str


# 它保存 S13 产生的上下文状态：
# messages           最终模型消息
# history_summary    历史摘要
# retrieval_context  检索资料
# citations          引用
# conflict           版本冲突
# context_tokens     上下文 token
@dataclass
class ContextState:
    messages: list[dict[str, Any]] = field(
        default_factory=list
    )
    history_summary: str = ""
    retrieval_context: list[dict[str, Any]] = field(
        default_factory=list
    )
    citations: list[dict[str, Any]] = field(
        default_factory=list
    )
    conflict: dict[str, Any] = field(
        default_factory=dict
    )
    context_tokens: int = 0
    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "history_summary": self.history_summary,
            "retrieval_context": self.retrieval_context,
            "citations": self.citations,
            "conflict": self.conflict,
            "context_tokens": self.context_tokens,
        }



# 它完整记录一次工具调用。
# 关键字段：
# tool_call_id   模型生成的唯一调用 ID
# tool_name      工具名称
# arguments      参数
# status         当前状态
# attempt        已经尝试多少次
# max_attempts   最多重试多少次
# result         成功结果
# error          错误信息
@dataclass
class ToolCallRecord:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(
        default_factory=dict
    )
    status: ToolCallStatus = ToolCallStatus.PENDING
    attempt: int = 0
    max_attempts: int = 3
    result: Any = None
    error: str = ""
    started_at: str = ""
    finished_at: str = ""

    # 执行中running
    def mark_running(self)->None:
        self.status=ToolCallStatus.RUNNING
        self.attempt+=1
        self.started_at=utc_now()
        self.error=""


    # 成功succeed
    def mark_succeeded(
            self,
            result:Any,
    )->None:
        self.status=ToolCallStatus.SUCCEEDED
        self.result=result
        self.finished_at=utc_now()


    # 失败failed
    def mark_failed(
            self,
            status:ToolCallStatus,
            error:str
    )->None:
        self.status=status
        self.error=error
        self.finished_at=utc_now()

    # 可以重连
    def can_retry(self)->bool:
        return (
            self.status
            in {
                ToolCallStatus.TIMED_OUT,
                ToolCallStatus.FAILED,
            }
            and self.attempt < self.max_attempts
        )

    def to_dict(self)->dict[str,Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "status": self.status.value,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

# run_id        本次任务唯一 ID
# thread_id     会话 ID，用于多轮恢复
# goal          用户目标
# status        整个任务状态
# current_node  当前执行节点
# step_count    已执行多少轮
# max_steps     最大循环次数
# context       上下文状态
# tool_calls    工具调用状态
# created_at    创建时间
# updated_at    更新时间
@dataclass
class RunState:
    run_id:str
    thread_id:str
    goal:str
    status:RunStatus=RunStatus.PENDING
    current_node:str="start"
    step_count:int=0
    max_steps:int=20
    context:ContextState=field(
        default_factory=ContextState
    )
    tool_calls:dict[str,ToolCallRecord]=field(
        default_factory=dict
    )
    created_at:str=field(
        default_factory=utc_now
    )
    updated_at:str=field(
        default_factory=utc_now
    )

    @classmethod
    def create(
        cls,
        thread_id:str,
        goal:str,
        max_steps:int=20,
    )->"RunState":
        return cls(
            run_id=str(uuid4()),
            thread_id=thread_id,
            goal=goal,
            max_steps=max_steps
        )
    
    # - **幂等注册工具调用**：重复 ID 直接返回 False，不重复创建
    # - 注册成功自动更新 `updated_at` 时间戳
    # - 返回布尔值让调用方感知是否是首次注册

    def register_tool_call(
            self,
            tool_call_id:str,
            tool_name:str,
            arguments:dict[str,Any],
    )->bool:
        if tool_call_id in self.tool_calls:
            return False
        self.tool_calls[tool_call_id]=ToolCallRecord(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
        )
        self.updated_at=utc_now()
        return True

    # - 门面模式：对外统一通过 `RunState` 操作子状态，不直接暴露 `ToolCallRecord` 的内部方法
    # - 每次状态变更都会同步刷新根状态的 `updated_at`，保证时间戳一致性
    def mark_tool_running(self,tool_call_id:str)->ToolCallRecord:
        record=self.tool_calls[tool_call_id]
        record.mark_running()
        self.updated_at=utc_now()
        return record

    # 同上，都是状态变更的代理方法，统一收口、统一更新时间
    def mark_tool_succeeded(
            self,
            tool_call_id:str,
            result:Any,
    )->ToolCallRecord:
        record=self.tool_calls[tool_call_id]
        record.mark_succeeded(result)
        self.updated_at=utc_now()
        return record

    def mark_tool_failed(
            self,
            tool_call_id:str,
            status:ToolCallStatus,
            error:str,
    )->ToolCallRecord:
        record=self.tool_calls[tool_call_id]
        record.mark_failed(status,error)
        self.updated_at=utc_now()
        return record

    # 步数递增，每完成一个完整的模型 - 工具循环计为一步
    def increment_step(self)->None:
        self.step_count+=1
        self.updated_at=utc_now()


    # - 任务继续执行的判断条件：任务处于运行中，且未达到最大步数
    # - 核心安全机制，避免模型死循环或异常流程导致步数爆炸
    def can_continue(self)->bool:
        return (
            self.status==RunStatus.RUNNING
            and self.step_count<self.max_steps
        )


    # - **递归序列化**：调用 `context.to_dict()` 和每条工具记录的 `to_dict()`，实现完整状态树的字典转换
    # - 所有枚举都通过 `.value` 转为字符串，保证 JSON 友好
    def to_dict(self)->dict[str,Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "goal": self.goal,
            "status": self.status.value,
            "current_node": self.current_node,
            "step_count": self.step_count,
            "max_steps": self.max_steps,
            "context": self.context.to_dict(),
            "tool_calls": {
                call_id: record.to_dict()
                for call_id, record
                in self.tool_calls.items()
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
# 失败决策引擎函数
def decide_failure(kind:FailureKind)->FailureDecision:
    #  **第一类：临时性故障**
    # - 场景：模型超时、工具超时、工具临时错误（如网络波动、下游服务临时不可用）
    # - 策略：允许重试，但必须先写检查点。防止进程崩溃恢复后，重复执行有副作用的工具
    if kind in {
        FailureKind.MODEL_TIMEOUT,
        FailureKind.TOOL_TIMEOUT,
        FailureKind.TOOL_TEMPORARY_ERROR
    }:
        return FailureDecision(
            retryable=True,
            checkpoint_required=True,
            terminal=False,
            reason="可重试，但重试前必须记录当前状态，避免重复执行副作用"
        )

    #  **第二类：持久化自身故障**
    # - 场景：检查点写入失败（数据库 / 磁盘异常）
    # - 策略：理论可重试，但必须先解决持久化问题，否则状态无法落盘，故障恢复后会出现重复执行
    if kind == FailureKind.CHECKPOINT_WRITE_ERROR:
        return FailureDecision(
            retryable=True,
            checkpoint_required=True,
            terminal=False,
            reason="必须先解决状态持久化，否则恢复后可能重复执行"
        )
    
    #  **第三类：幂等命中**
    # - 场景：重复的工具调用 ID
    # - 策略：禁止重试，直接复用已有结果；但仍需记录状态，保证链路完整
    if kind == FailureKind.DUPLICATE_TOOL_CALL:
        return FailureDecision(
            retryable=False,
            checkpoint_required=True,
            terminal=False,
            reason="复用已有 tool_call_id 结果，不能再次执行工具"
        )

    #  **第四类：逻辑类错误**
    # - 场景：模型输出格式错误、工具业务参数错误、工具不存在
    # - 策略：原样重试必然失败，需要修改参数 / 上下文；不直接终止任务，给上层修正的机
    if kind in {
        FailureKind.MODEL_FORMAT_ERROR,
        FailureKind.TOOL_BUSINESS_ERROR,
        FailureKind.TOOL_UNKNOWN,
    }:
        return FailureDecision(
            retryable=False,
            checkpoint_required=True,
            terminal=False,
            reason="需要修改上下文或终止任务，不能原样重试"
        )

    #  - **第五类：终止性错误（兜底）**
    #   - 场景：权限不足、用户取消、审批超时、重试耗尽等所有未匹配的错误
    #   - 策略：不可重试，任务直接终止，所有场景都必须写入检查点留痕
    # > 核心设计原则：**所有失败都必须持久化**；默认不可重试，只有明确的临时性故障才允许重试。
    return FailureDecision(
        retryable=False,
        checkpoint_required=True,
        terminal=True,
        reason="不可恢复或需要人工处理"
    )

def main()->int:
    # 1. 创建任务：指定会话 ID 和目标，自动生成运行 ID
    # 2. 启动任务：将状态从 PENDING 改为 RUNNING
    state=RunState.create(
        thread_id="thread-1",
        goal="检查仓库并修复 CI失败"
    )

    state.status=RunStatus.RUNNING

    # 1. 首次注册工具：返回 `True`
    # 2. 重复注册同一个 ID：返回 `False`，验证幂等性生效
    registered=state.register_tool_call(
        tool_call_id="call-1",
        tool_name="shell.run",
        arguments={"command":"pytest -q"}
    )
    duplicate_registered = state.register_tool_call(
        tool_call_id="call-1",
        tool_name="shell.run",
        arguments={"command": "pytest -q"},
    )

    # 1. 标记工具开始执行
    # 2. 标记工具执行成功，传入返回结果（退出码 + 标准输出）
    # 3. 完成一个循环，步数 + 1
    state.mark_tool_running("call-1")
    state.mark_tool_succeeded(
        "call-1",
        {"exit_code":0,"stdout":"2 passed"}
    )
    state.increment_step()

    payload = {
        "registered": registered,
        "duplicate_registered": duplicate_registered,
        "failure_model_timeout": decide_failure(FailureKind.MODEL_TIMEOUT).__dict__,
        "failure_permission": decide_failure(FailureKind.TOOL_PERMISSION_DENIED).__dict__,
        "state": state.to_dict(),
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








    

