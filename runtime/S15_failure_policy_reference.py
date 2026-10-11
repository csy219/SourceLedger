# 这是一套**生产级精细化故障策略决策引擎**，是对前序基础失败判断的升级。
# 核心是将「简单的是否可重试」升级为「明确的行动指令 + 退避时长 + 副作用安全校验」，
# 覆盖 9 种标准化故障处理动作，内置指数退避算法，支持副作用感知，
# 是 Agent 编排体系中故障容错能力的核心决策模块。

import json
# 导入 `asdict` 用于将数据类转为普通字典，方便 JSON 序列化
from dataclasses import dataclass,asdict
from enum import Enum

from runtime.S15_state_reference import FailureKind

# 2. 故障处理动作枚举
# 动作枚举	核心含义	对应后续流程
# RETRY_TOOL	重试当前工具调用	延迟后重新执行工具逻辑
# RETRY_MODEL	重试当前模型调用	延迟后重新发起模型推理
# RECALL_MODEL	召回模型重新决策	将错误作为观测写入上下文，让模型基于错误调整方案
# REPAIR_CONTEXT	修复上下文	修正上下文内容（补充工具列表、修复格式约束）后再执行
# WAIT_APPROVAL	等待人工审批	暂停任务，等待人工介入处理
# VERIFY_SIDE_EFFECT	验证副作用	先核对工具实际执行状态，再决定后续操作
# REUSE_RESULT	复用已有结果	直接使用历史工具调用结果，不重复执行
# RETRY_CHECKPOINT	重试检查点写入	延迟后重新尝试持久化状态
# TERMINATE	终止任务	直接结束任务，标记为失败
class FailureAction(str,Enum):
    RETRY_TOOL="retry_tool"
    RETRY_MODEL="retry_model"
    RECALL_MODEL="recall_model"
    REPAIR_CONTEXT="repair_context"
    WAIT_APPROVAL="wait_approval"
    VERIFY_SIDE_EFFECT="verify_side_effect"
    REUSE_RESULT="reuse_result"
    RETRY_CHECKPOINT="retry_checkpoint"
    TERMINATE="terminate"

# 3. 故障决策结果结构体
# **不可变决策对象**（`frozen=True` 修饰），一旦创建不可修改，保证线程安全与决策一致性。
# - `action`：核心处理动作指令
# - `retryable`：是否可重试（兼容旧版判断逻辑）
# - `checkpoint_required`：处理前是否必须持久化检查点
# - `terminal`：是否为终止性错误
# - `retry_delay_ms`：重试延迟毫秒数，配合指数退避算法
# - `reason`：决策说明，用于日志排查与问题定位
@dataclass(frozen=True)
class FailurePolicyDecision:
    action:FailureAction
    retryable:bool
    checkpoint_required:bool
    terminal:bool
    retry_delay_ms:int
    reason:str


# 4. 指数退避算法
# 实现**二进制指数退避策略**，用于控制重试间隔，避免密集重试加剧下游故障（故障风暴）。
# 1. `safe_attempt` 保底为 1，避免 0 或负数导致计算错误
# 2. 延迟公式：`基础延迟 × 2^(尝试次数-1)`
# 3. 最终延迟不超过 `max_delay_ms` 上限
def calculate_backoff_ms(
    attempt:int,
    base_delay_ms:int=250,
    max_delay_ms:int=5000,
):
    safe_attempt=max(1,attempt)
    delay=base_delay_ms*(2**(safe_attempt-1))
    return min(delay,max_delay_ms)

# 重试决策工厂函数
# 设计价值：抽离公共重试逻辑，后续新增故障类型时直接调用即可，保证所有重试策略全局一致。
def retry_decision(
    action:FailureAction,
    attempt:int,
    max_attempts:int,
    reason:str,
)->FailurePolicyDecision:
    if attempt < max_attempts:
        return FailurePolicyDecision(
            action=action,
            retryable=True,
            checkpoint_required=True,
            terminal=False,
            retry_delay_ms=calculate_backoff_ms(attempt),
            reason=reason,
        )
    return FailurePolicyDecision(
        action=FailureAction.TERMINATE,
        retryable=False,
        checkpoint_required=True,
        terminal=True,
        retry_delay_ms=0,
        reason="重试次数已经耗尽",
    )

# 核心故障决策函数 `decide_failure`
def decide_failure(
    kind:FailureKind,
    attempt:int=1,
    max_attempts:int=3,

    # 是否已产生副作用
    side_effect_committed:bool=False,
)->FailurePolicyDecision:
    if kind==FailureKind.MODEL_TIMEOUT:
        return retry_decision(
            action=FailureAction.RETRY_MODEL,
            attempt=attempt,
            max_attempts=max_attempts,
            reason="模型调用超时, 可以重新调用模型"
        )

    if kind==FailureKind.TOOL_TIMEOUT:
        if side_effect_committed:
            return FailurePolicyDecision(
                action=FailureAction.VERIFY_SIDE_EFFECT,
                retryable=False,
                checkpoint_required=True,
                terminal=False,
                retry_delay_ms=0,
                reason=("工具可能产生副作用, 不能直接重试,必须先核对状态")
            )
        return retry_decision(
            action=FailureAction.RETRY_TOOL,
            attempt=attempt,
            max_attempts=max_attempts,
            reason=(
                "工具超时且没有副作用，"
                "可以延迟后重试"
            ),
        )
    if kind == FailureKind.TOOL_TEMPORARY_ERROR:
        return retry_decision(
            action=FailureAction.RETRY_TOOL,
            attempt=attempt,
            max_attempts=max_attempts,
            reason="工具临时错误，可以延迟后重试",
        )
    if kind == FailureKind.CHECKPOINT_WRITE_ERROR:
        return FailurePolicyDecision(
            action=FailureAction.RETRY_CHECKPOINT,
            retryable=True,
            checkpoint_required=True,
            terminal=False,
            retry_delay_ms=calculate_backoff_ms(
                attempt
            ),
            reason=(
                "状态没有保存成功，"
                "不能继续执行有副作用的工具"
            ),
        )
    if kind == FailureKind.DUPLICATE_TOOL_CALL:
        return FailurePolicyDecision(
            action=FailureAction.REUSE_RESULT,
            retryable=False,
            checkpoint_required=False,
            terminal=False,
            retry_delay_ms=0,
            reason=(
                "相同 tool_call_id 已经存在，"
                "直接复用已有结果"
            ),
        )
    if kind == FailureKind.MODEL_FORMAT_ERROR:
        return FailurePolicyDecision(
            action=FailureAction.REPAIR_CONTEXT,
            retryable=False,
            checkpoint_required=True,
            terminal=False,
            retry_delay_ms=0,
            reason=(
                "模型输出格式不符合协议，"
                "需要修复上下文或输出解析器"
            ),
        )
    if kind == FailureKind.TOOL_BUSINESS_ERROR:
        return FailurePolicyDecision(
            action=FailureAction.RECALL_MODEL,
            retryable=False,
            checkpoint_required=True,
            terminal=False,
            retry_delay_ms=0,
            reason=(
                "工具业务错误需要作为 Observation "
                "返回模型，让模型重新决策"
            ),
        )

    if kind == FailureKind.TOOL_PERMISSION_DENIED:
        return FailurePolicyDecision(
            action=FailureAction.WAIT_APPROVAL,
            retryable=False,
            checkpoint_required=True,
            terminal=False,
            retry_delay_ms=0,
            reason=(
                "权限拒绝，不能自动重试，"
                "需要人工审批或修改权限"
            ),
        )

    if kind == FailureKind.TOOL_UNKNOWN:
        return FailurePolicyDecision(
            action=FailureAction.REPAIR_CONTEXT,
            retryable=False,
            checkpoint_required=True,
            terminal=False,
            retry_delay_ms=0,
            reason=(
                "模型请求了不存在的工具，"
                "需要把可用工具列表返回模型"
            ),
        )

    if kind == FailureKind.USER_CANCELLED:
        return FailurePolicyDecision(
            action=FailureAction.TERMINATE,
            retryable=False,
            checkpoint_required=True,
            terminal=True,
            retry_delay_ms=0,
            reason="用户主动取消任务",
        )

    if kind == FailureKind.APPROVAL_TIMEOUT:
        return FailurePolicyDecision(
            action=FailureAction.TERMINATE,
            retryable=False,
            checkpoint_required=True,
            terminal=True,
            retry_delay_ms=0,
            reason="人工审批超时，任务终止",
        )

    return FailurePolicyDecision(
        action=FailureAction.TERMINATE,
        retryable=False,
        checkpoint_required=True,
        terminal=True,
        retry_delay_ms=0,
        reason="没有匹配到可恢复策略",
    )

def main() -> int:
    cases = [
        (
            FailureKind.MODEL_TIMEOUT,
            1,
            3,
            False,
        ),
        (
            FailureKind.TOOL_TIMEOUT,
            1,
            3,
            False,
        ),
        (
            FailureKind.TOOL_TIMEOUT,
            1,
            3,
            True,
        ),
        (
            FailureKind.TOOL_TEMPORARY_ERROR,
            2,
            3,
            False,
        ),
        (
            FailureKind.TOOL_TEMPORARY_ERROR,
            3,
            3,
            False,
        ),
        (
            FailureKind.TOOL_PERMISSION_DENIED,
            1,
            3,
            False,
        ),
        (
            FailureKind.DUPLICATE_TOOL_CALL,
            1,
            3,
            False,
        ),
        (
            FailureKind.CHECKPOINT_WRITE_ERROR,
            1,
            3,
            False,
        ),
    ]

    rows = []

    for (
        kind,
        attempt,
        max_attempts,
        side_effect_committed,
    ) in cases:
        decision = decide_failure(
            kind=kind,
            attempt=attempt,
            max_attempts=max_attempts,
            side_effect_committed=(
                side_effect_committed
            ),
        )
        rows.append(
            {
                "failure_kind": kind.value,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "side_effect_committed": (
                    side_effect_committed
                ),
                "decision": {
                    **asdict(decision),
                    "action": (
                        decision.action.value
                    ),
                },
            }
        )

    print(
        json.dumps(
            rows,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())