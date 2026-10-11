### 一、代码整体定位
# 这段代码实现了 **Agent 编排引擎的三大底层基础组件**：
# 1. **表驱动有限状态机（FSM）**：严格约束任务状态的合法流转，杜绝非法状态跳转
# 2. **通用幂等存储**：标准化操作级别的去重能力，支持任意操作的幂等控制
# 3. **检查点策略引擎**：定义不同事件节点的持久化要求与级别，保障故障恢复的安全性
# 三者均为纯 Python 标准库实现，无外部依赖，是构建可靠、可恢复 Agent 运行时的核心基础设施。
import json
from dataclasses import asdict, dataclass
from enum import Enum

from runtime.S15_state_reference import RunStatus

# 2. 状态转换事件枚举
class TransitionEvent(str, Enum):
    START_RUN = "start_run"
    REQUIRE_APPROVAL = "require_approval"
    APPROVE = "approve"
    REJECT = "reject"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"
    RETRY = "retry"

# 3. 自定义异常
class TransitionError(ValueError):
    pass


# 4. 核心：状态转换表（表驱动 FSM）
# 这是**表驱动有限状态机**的核心实现，用二维字典结构定义：`当前状态 → 事件 → 目标状态`。
# 当前状态	允许事件	目标状态
# 待执行（PENDING）	启动任务	运行中（RUNNING）
# 待执行（PENDING）	取消任务	已取消（CANCELLED）
# 运行中（RUNNING）	请求审批	待审批（WAITING_APPROVAL）
# 运行中（RUNNING）	任务完成	已完成（COMPLETED）
# 运行中（RUNNING）	任务失败	已失败（FAILED）
# 运行中（RUNNING）	取消任务	已取消（CANCELLED）
# 待审批（WAITING_APPROVAL）	审批通过	运行中（RUNNING）
# 待审批（WAITING_APPROVAL）	审批拒绝	已失败（FAILED）
# 待审批（WAITING_APPROVAL）	取消任务	已取消（CANCELLED）
# 已完成（COMPLETED）	无	终态，不可跳转
# 已失败（FAILED）	重试任务	运行中（RUNNING）
# 已取消（CANCELLED）	无	终态，不可跳转
TRANSITIONS: dict[RunStatus, dict[TransitionEvent, RunStatus]] = {
    RunStatus.PENDING: {
        TransitionEvent.START_RUN: RunStatus.RUNNING,
        TransitionEvent.CANCEL: RunStatus.CANCELLED,
    },
    RunStatus.RUNNING: {
        TransitionEvent.REQUIRE_APPROVAL: RunStatus.WAITING_APPROVAL,
        TransitionEvent.COMPLETE: RunStatus.COMPLETED,
        TransitionEvent.FAIL: RunStatus.FAILED,
        TransitionEvent.CANCEL: RunStatus.CANCELLED,
    },
    RunStatus.WAITING_APPROVAL: {
        TransitionEvent.APPROVE: RunStatus.RUNNING,
        TransitionEvent.REJECT: RunStatus.FAILED,
        TransitionEvent.CANCEL: RunStatus.CANCELLED,
    },
    RunStatus.COMPLETED: {},
    RunStatus.FAILED: {
        TransitionEvent.RETRY: RunStatus.RUNNING,
    },
    RunStatus.CANCELLED: {},
}


# 5. 状态转换执行函数
# 1. 根据当前状态查表获取允许的事件集合
# 2. 事件不在允许列表中 → 抛出 `TransitionError` 非法转换异常
# 3. 合法则返回目标状态
# > 设计原则：**状态机只负责状态跳转，不执行业务逻辑**，保持单一职责。
def next_status(
        current:RunStatus,
        event:TransitionEvent,
)->RunStatus:
    allowed=TRANSITIONS.get(current,{})

    if event not in allowed:
        raise TransitionError(
            f"非法状态转换: "
            f"{current.value} -> "
            f"{event.value}"
        )

    return allowed[event]

# 6. 幂等组件：操作状态枚举
# 定义单次幂等操作的生命周期状态：已开始、已成功、已失败。
class OperationStatus(str,Enum):
    STARTED="started"
    SUCCEEDED="succeeded"
    FAILED="failed"

# 7. 幂等记录结构体
# 存储单次幂等操作的完整信息：
# - `key`：幂等唯一标识（如 tool_call_id）
# - `status`：操作当前状态
# - `result`：成功时的返回结果
# - `error`：失败时的错误信息
@dataclass
class IdempotencyRecord:
    key:str
    status:OperationStatus=OperationStatus.STARTED
    result:object | None=None
    error:str=""


# 8. 幂等存储器
class IdempotencyStore:
    # 通用幂等存储，内部用字典维护所有幂等记录，可扩展为数据库 / Redis 实现。
    def __init__(self)->None:
        self.records:dict[str,IdempotencyRecord,]={}

    #     **幂等控制的核心逻辑**：
    # - 传入幂等键，已存在则返回 `False` + 已有记录（不重复执行）
    # - 不存在则创建新记录，状态初始化为 `STARTED`，返回 `True` + 新记录（允许执行）
    # - 返回布尔值让调用方快速判断是否是首次执行
    def begin(
            self,
            key:str,
    )->tuple[bool,IdempotencyRecord]:
        existing=self.records.get(key)
        if existing is not None:
            return False,existing
        record=IdempotencyRecord(key=key)
        self.records[key]=record
        return True,record
    # complete 方法（标记成功）
    def complete(self,key:str,result:object)->IdempotencyRecord:
        record=self.records.get(key)
        record.status = OperationStatus.SUCCEEDED
        record.result = result
        record.error = ""
        return record
    # fail 方法（标记失败）
    #     操作失败时调用，更新状态为失败，存入错误信息。
    # > 设计价值：通用幂等能力，不仅限于工具调用，任何需要去重的操作（模型调用、审批、通知等）都可以复用。
    def fail(self, key: str, error: str) -> IdempotencyRecord:
        record = self.records[key]
        record.status = OperationStatus.FAILED
        record.error = error
        return record


# 9. 检查点策略组件
# 检查点事件枚举
# 定义任务生命周期中所有需要考虑持久化的关键节点，共 8 个
class CheckpointEvent(str, Enum):
    RUN_STARTED = "run_started"
    MODEL_RESPONSE_RECEIVED = "model_response_received"
    TOOL_CALL_REGISTERED = "tool_call_registered"
    BEFORE_SIDE_EFFECT = "before_side_effect"
    AFTER_SIDE_EFFECT = "after_side_effect"
    APPROVAL_REQUIRED = "approval_required"
    FINAL_ANSWER = "final_answer"
    FAILURE = "failure"

# 检查点计划结构体
# 不可变对象，封装单个事件的持久化策略：
# - `required`：是否必须持久化
# - `durability`：持久化级别：`sync`（同步强持久化）、`none`（不持久化）
# - `reason`：策略说明，用于文档化和排查
@dataclass
class CheckpointPlan:
    required:bool
    durability:str
    reason:str

    # 检查点策略函数
    # 事件节点	是否必须持久化	持久化级别	核心原因
    # 任务启动	✅	sync	记录任务已启动，避免重复启动
    # 模型响应收到	✅	sync	记录模型决策，故障恢复后不重复调用模型
    # 工具调用注册	✅	sync	记录 tool_call_id，实现幂等保护
    # 副作用执行前	✅	sync	关键安全点：写入执行意图，崩溃后可判断「可能已执行」，禁止直接重试
    # 副作用执行后	✅	sync	关键安全点：写入执行结果，崩溃后可直接复用，避免重复执行副作用
    # 需要审批	✅	sync	保存待审批状态，等待人工介入
    # 最终回答	✅	sync	保存终态和最终结果
    # 失败	✅	sync	记录失败原因、尝试次数、恢复点
    # 其他未知事件	❌	none	无需持久化
def checkpoint_plan(
            event: CheckpointEvent,
        )->CheckpointPlan:
        if event == CheckpointEvent.RUN_STARTED:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason="记录任务已经启动",
            )

        if event == (
            CheckpointEvent.MODEL_RESPONSE_RECEIVED
        ):
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason=(
                    "记录模型决策，"
                    "避免恢复后重复决策"
                ),
            )

        if event == CheckpointEvent.TOOL_CALL_REGISTERED:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason=(
                    "记录 tool_call_id，实现幂等保护"
                ),
            )

        if event == CheckpointEvent.BEFORE_SIDE_EFFECT:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason=(
                    "有副作用的工具执行前必须写入意图，"
                    "崩溃后才能判断是否可能已经执行"
                ),
            )

        if event == CheckpointEvent.AFTER_SIDE_EFFECT:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason=(
                    "记录工具结果或外部副作用状态，"
                    "避免恢复后重复执行"
                ),
            )

        if event == CheckpointEvent.APPROVAL_REQUIRED:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason="保存等待审批的状态",
            )

        if event == CheckpointEvent.FINAL_ANSWER:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason="保存最终结果和终态",
            )

        if event == CheckpointEvent.FAILURE:
            return CheckpointPlan(
                required=True,
                durability="sync",
                reason=(
                    "记录失败原因、尝试次数和恢复点"
                ),
            )

        return CheckpointPlan(
            required=False,
            durability="none",
            reason="该事件不需要持久化",
        )
def main()->int:
    # ① 状态机流程测试
    # 模拟一条完整的合法流转链路：
    # `待执行 → 启动 → 运行中 → 请求审批 → 待审批 → 审批通过 → 运行中 → 完成 → 已完成`
    transitions=[]
    status=RunStatus.PENDING

    for event in [
        TransitionEvent.START_RUN,
        TransitionEvent.REQUIRE_APPROVAL,
        TransitionEvent.APPROVE,
        TransitionEvent.COMPLETE
    ]:
        previous=status
        status=next_status(status,event)
        transitions.append(
            {
                "from":previous.value,
                "event":event.value,
                "to":status.value,
            }
        )
    # ② 非法转换验证
    invalid_transition_error=""

    try:
        next_status(
            RunStatus.COMPLETED,
            TransitionEvent.START_RUN,
        )
    except TransitionError as exc:
        invalid_transition_error=str(exc)


    # ③ 幂等功能测试
    idempotency = IdempotencyStore()
    first_allowed, first_record = idempotency.begin("tool-call-1")
    duplicate_allowed, duplicate_record = idempotency.begin("tool-call-1")
    first_status = first_record.status.value
    duplicate_status = duplicate_record.status.value
    idempotency.complete("tool-call-1", {"exit_code": 0})
    completed_record = idempotency.records["tool-call-1"]


    # ④ 检查点策略遍历
    checkpoint_events = [
        CheckpointEvent.RUN_STARTED,
        CheckpointEvent.MODEL_RESPONSE_RECEIVED,
        CheckpointEvent.TOOL_CALL_REGISTERED,
        CheckpointEvent.BEFORE_SIDE_EFFECT,
        CheckpointEvent.AFTER_SIDE_EFFECT,
        CheckpointEvent.APPROVAL_REQUIRED,
        CheckpointEvent.FINAL_ANSWER,
        CheckpointEvent.FAILURE,
    ]
    checkpoint_plans = [
        {"event": event.value, **asdict(checkpoint_plan(event)),}
        for event in checkpoint_events
    ]

    # ⑤ 结果输出
    output = {
        "transitions": transitions,
        "invalid_transition_error": invalid_transition_error,
        "idempotency": {
            "first_allowed": first_allowed,
            "duplicate_allowed": duplicate_allowed,
            "first_status": first_status,
            "duplicate_status": duplicate_status,
            "completed_record": {
                **asdict(completed_record),
                "status": (
                    completed_record.status.value
                ),
            },
        },
        "checkpoint_plans": checkpoint_plans,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
