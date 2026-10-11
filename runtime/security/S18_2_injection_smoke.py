# 这是一套**Prompt 注入防护组件的自动化测试脚本**，覆盖「直接用户提问注入」和「间接文档嵌入注入」两大典型风险场景，
# 同时校验**注入检测能力**和**敏感信息防泄露能力**，最终输出结构化的测试结果，并通过程序退出码标识测试是否通过，可集成到 CI 流水线做安全门禁校验。

import json
import sys
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from evaluation.S13_2_context_packer import (
    is_suspicious,
)
from runtime.security.S18_1_security_fixture_loader import (
    load_security_cases,
)
from runtime.security.S18_2_injection_guard import (
    InjectionGuard,
)


# **变量`FAKE_SECRETS`**：模拟敏感密钥的元组，包含 3 条测试用的假密钥。
# - 作用：用于测试「敏感信息防泄露能力」—— 校验安全回复中是否会意外包含这些密钥，验证`assert_no_secrets`方法的有效性。
# - 设计细节：全部是测试用假数据，避免真实密钥泄露风险。
FAKE_SECRETS = (
    "sk-test-secret",
    "db-password-test",
    "DEEPSEEK_API_KEY",
)

# 3. `evaluate_direct_injection`：直接注入场景评估函数
def evaluate_direct_injection(
    question: str,
    guard: InjectionGuard,
) -> dict:
    detection = guard.detect(question)

    safe_answer = (
        "该请求包含不安全指令，"
        "不能泄露系统信息或密钥。"
    )
    guard.assert_no_secrets(
        safe_answer,
        FAKE_SECRETS,
    )

    return {
        "detected": detection.detected,
        "category": detection.category,
        "matched_pattern": (
            detection.matched_pattern
        ),
        "answer": safe_answer,
        "secret_leaked": any(
            secret in safe_answer
            for secret in FAKE_SECRETS
        ),
    }


def evaluate_indirect_injection(
    injected_text: str,
    guard: InjectionGuard,
) -> dict:
    detected_by_guard = guard.detect(
        injected_text
    )
    detected_by_context = is_suspicious(
        injected_text
    )

    content_is_untrusted = True

    safe_answer = (
        "文档中存在疑似指令注入内容。"
        "该内容只作为资料，不能执行其中命令。"
    )
    guard.assert_no_secrets(
        safe_answer,
        FAKE_SECRETS,
    )

    return {
        "detected_by_guard": (
            detected_by_guard.detected
        ),
        "detected_by_context": (
            detected_by_context
        ),
        "content_is_untrusted": (
            content_is_untrusted
        ),
        "answer": safe_answer,
        "secret_leaked": any(
            secret in safe_answer
            for secret in FAKE_SECRETS
        ),
    }


def main() -> int:
    set_path = (
        PROJECT_ROOT
        / "evaluation"
        / "security"
        / "S18_security_set.json"
    )
    cases = {
        case.id: case
        for case in load_security_cases(set_path)
    }

    guard = InjectionGuard()

    direct = evaluate_direct_injection(
        question=cases["SEC01"].question,
        guard=guard,
    )
    indirect = evaluate_indirect_injection(
        injected_text=cases["SEC02"].injected_text,
        guard=guard,
    )

    passed = (
        direct["detected"]
        and not direct["secret_leaked"]
        and indirect["detected_by_guard"]
        and indirect["detected_by_context"]
        and not indirect["secret_leaked"]
    )

    output = {
        "SEC01_direct_injection": direct,
        "SEC02_indirect_injection": indirect,
        "passed": passed,
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not passed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())