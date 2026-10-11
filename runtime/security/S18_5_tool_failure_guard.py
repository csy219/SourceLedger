# 这是**Agent 工具调用的安全防护与故障标准化处理模块**，核心实现两大能力：

# 1. **命令安全拦截**：基于正则规则识别危险系统命令，从源头拦截高危操作（如删根、格式化、下载执行脚本等）
# 2. **故障统一治理**：封装工具执行的全流程，统一捕获各类异常、标准化执行结果，同时给出重试建议、人工检查标记、状态分类，是 Agent 工具调用层的容错与安全底座。

import re
from dataclasses import dataclass
from typing import Any, Callable

from runtime.S15_state_reference import (
    ToolCallStatus,
)


@dataclass(frozen=True)
class CommandDecision:

    # - `allowed: bool`：布尔标记，`True`代表命令允许执行，`False`代表命令被拦截。
    # - `reason: str`：决策原因编码，拦截时为危险模式的类别名（如`delete_root`），放行时为固定字符串`allowed`。
    # - `matched_pattern: str`：实际匹配到的危险命令片段，拦截时用于日志定位，放行时为空字符串。
    allowed: bool
    reason: str
    matched_pattern: str



# - `command: str`：本次尝试执行的原始命令字符串。
# - `attempted: bool`：是否发起了执行尝试，被安全拦截时为`False`，进入执行流程后为`True`。
# - `executed: bool`：命令是否实际落地执行，权限错误、安全拦截时为`False`，超时、通用异常、正常执行时为`True`。
# - `status: ToolCallStatus`：工具调用的标准状态枚举值，用于上层流程统一判断。
# - `exit_code: int | None`：命令进程的退出码，0 代表成功，非 0 代表失败；未执行到进程退出时为`None`。
# - `stdout: str`：命令的标准输出内容。
# - `stderr: str`：命令的标准错误内容，异常时存储异常信息。
# - `retryable: bool`：标记该失败是否可以重试，用于上层重试策略判断。
# - `manual_check_required: bool`：标记是否需要人工介入检查，用于副作用已发生、结果不确定的场景。
# - `reason: str`：结果原因编码，用于日志排查和流程分支判断。
@dataclass(frozen=True)
class ToolFailureReport:
    command: str
    attempted: bool
    executed: bool
    status: ToolCallStatus
    exit_code: int | None
    stdout: str
    stderr: str
    retryable: bool
    manual_check_required: bool
    reason: str

class CommandPolicy:
    def __init__(
        self,
        blocked_patterns:list[tuple[str,re.Pattern[str]]] | None=None,
    )->None:
        self.blocked_patterns = (
            blocked_patterns
            if blocked_patterns is not None
            else [
                (
                    "delete_root",
                    re.compile(
                        r"rm\s+-rf\s+/(?:\s|$)"
                    ),
                ),
                (
                    "delete_recursive",
                    re.compile(
                        r"rm\s+-rf\s+"
                    ),
                ),
                (
                    "windows_format",
                    re.compile(
                        r"(?:format|diskpart)\b",
                        re.IGNORECASE,
                    ),
                ),
                (
                    "windows_force_delete",
                    re.compile(
                        r"del\s+/f\s+/s\s+/q",
                        re.IGNORECASE,
                    ),
                ),
                (
                    "pipe_to_shell",
                    re.compile(
                        r"(curl|wget).*\|\s*(bash|sh)",
                        re.IGNORECASE,
                    ),
                ),
            ]
        )

    def check(
        self,
        command:str,
    )->CommandDecision:
        for reason,pattern in (self.blocked_patterns):
            match=pattern.search(command)

            if match:
                return CommandDecision(
                    allowed=False,
                    reason=reason,
                    matched_pattern=match.group(0)
                )

        return CommandDecision(
            allowed=True,
            reason="allowed",
            matched_pattern=""
        )


class ToolFailureGuard:
    def __init__(
        self,
        command_policy: CommandPolicy | None = None,
    ) -> None:
        self.command_policy = (
            command_policy or CommandPolicy()
        )


    # - `command: str`：待执行的命令字符串，用于安全检查和结果记录；
    # - `func: Callable[[], Any]`：实际执行命令的可调用对象，无入参，返回执行结果；
    # - `side_effect_committed: bool = False`：副作用标记，代表命令是否已经产生了不可逆的副作用（如数据已写入、文件已修改），默认`False`。
    def execute(
        self,
        command: str,
        func: Callable[[], Any],
        side_effect_committed: bool = False,
    ) -> ToolFailureReport:

        # 第一步：前置安全拦截

        # - 先调用策略检查命令是否合法；
        # - 若被拦截，直接返回拒绝报告：
        # - 未尝试执行、未实际执行，状态为`REJECTED`；
        # - 不可重试、无需人工检查；
        # - 原因标记为危险命令拦截 + 具体危险类型。
        decision = self.command_policy.check(
            command
        )

        if not decision.allowed:
            return ToolFailureReport(
                command=command,
                attempted=False,
                executed=False,
                status=ToolCallStatus.REJECTED,
                exit_code=None,
                stdout="",
                stderr="",
                retryable=False,
                manual_check_required=False,
                reason=(
                    "dangerous_command_blocked:"
                    f"{decision.reason}"
                ),
            )


        ##### 第二步：执行函数与异常捕获
        try:
            result = func()
        # 异常分支 1：超时异常
        # - 捕获`TimeoutError`超时异常，代表命令执行超时；
        # - 标记为已尝试、已执行，状态`TIMED_OUT`；
        # - 重试与人工检查逻辑：
        # - 未产生副作用：可重试，无需人工检查，原因为`tool_timeout`；
        # - 已产生副作用：不可重试，需要人工检查，原因为`side_effect_may_have_happened`（副作用可能已发生，结果不确定）。
        except TimeoutError as exc:
            return ToolFailureReport(
                command=command,
                attempted=True,
                executed=True,
                status=ToolCallStatus.TIMED_OUT,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                retryable=(
                    not side_effect_committed
                ),
                manual_check_required=(
                    side_effect_committed
                ),
                reason=(
                    "tool_timeout"
                    if not side_effect_committed
                    else "side_effect_may_have_happened"
                ),
            )

        # 异常分支 2：权限错误
        except PermissionError as exc:
            return ToolFailureReport(
                command=command,
                attempted=True,
                executed=False,
                status=ToolCallStatus.REJECTED,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                retryable=False,
                manual_check_required=False,
                reason="permission_denied",
            )
        # 异常分支 3：通用异常
        except Exception as exc:
            return ToolFailureReport(
                command=command,
                attempted=True,
                executed=True,
                status=ToolCallStatus.FAILED,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                retryable=True,
                manual_check_required=False,
                reason="tool_exception",
            )
        # 子场景 A：结果为字典格式（标准命令执行结果）
        if isinstance(result, dict):
            exit_code = result.get("exit_code")
            stdout = str(
                result.get("stdout", "")
            )
            stderr = str(
                result.get("stderr", "")
            )


            # - 非零退出码判定为执行失败；
            # - 返回失败报告，状态`FAILED`，原因为`non_zero_exit`，标记为可重试。
            if (
                exit_code is not None
                and int(exit_code) != 0
            ):
                return ToolFailureReport(
                    command=command,
                    attempted=True,
                    executed=True,
                    status=ToolCallStatus.FAILED,
                    exit_code=int(exit_code),
                    stdout=stdout,
                    stderr=stderr,
                    retryable=True,
                    manual_check_required=False,
                    reason="non_zero_exit",
                )

            # - 退出码为 0（或无退出码），判定为执行成功；
            # - 返回成功报告，状态`SUCCEEDED`，原因为`success`，不可重试。
            return ToolFailureReport(
                command=command,
                attempted=True,
                executed=True,
                status=ToolCallStatus.SUCCEEDED,
                exit_code=(
                    int(exit_code)
                    if exit_code is not None
                    else 0
                ),
                stdout=stdout,
                stderr=stderr,
                retryable=False,
                manual_check_required=False,
                reason="success",
            )
        # 子场景 B：结果为非字典格式（直接返回内容）
        # - 执行函数直接返回字符串、数字等非字典结果时，统一包装为成功报告；
        # - 默认退出码 0，输出内容转为`stdout`，状态`SUCCEEDED`。
        return ToolFailureReport(
            command=command,
            attempted=True,
            executed=True,
            status=ToolCallStatus.SUCCEEDED,
            exit_code=0,
            stdout=str(result),
            stderr="",
            retryable=False,
            manual_check_required=False,
            reason="success",
        )
        
### 三、核心设计总结

# 1. **前置安全 + 后置容错**：先通过正则规则做高危命令拦截，再通过全量异常捕获做执行容错，覆盖工具调用的安全与稳定性两大风险。
# 2. **标准化结果输出**：所有场景都统一为`ToolFailureReport`结构，上层无需关心底层差异，只需通过`status`、`retryable`等字段做流程判断。
# 3. **副作用感知设计**：通过`side_effect_committed`参数区分失败场景的重试策略和人工检查要求，避免副作用场景下盲目重试导致数据异常。
# 4. **可扩展配置**：支持自定义拦截规则和自定义执行函数，既能适配不同安全等级的业务场景，也能包裹任意类型的工具执行逻辑。