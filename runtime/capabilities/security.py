# 这是 **C06 安全类能力封装层**，和之前的检索、弹性能力封装属于同一层级，作用是把底层 S18 系列的安全防护原语（注入检测、无证据拒答），
# 封装成符合标准 `Capability` 契约的可调用服务，自动带上**全链路安全事件追踪、参数校验、结构化输入输出**，可通过统一 HTTP 接口直接调用调试，也可以嵌入业务链路作为安全护栏。

# 简单说：把底层的纯技术安全检测函数，包装成了**可观测、可测试、可接入业务流程**的标准化安全能力。
# 层级	内容	定位
# 底层	S18 安全原语：InjectionGuard / NoEvidencePolicy	纯技术检测函数，只做功能，无追踪、无接口
# 本层	两个 Security Capability 处理器	适配层：参数解析、事件埋点、标准化输入输出
# 上层	Capability 注册中心 + FastAPI 路由	对外暴露成 HTTP 服务，或嵌入业务链路


"""Security capability handlers over S18 guards."""

from __future__ import annotations

from typing import Any

from runtime.api.capabilities import (
    CapabilityDefinition,
    CapabilityDescriptor,
    CapabilityRegistry,
    CapabilityRunRequest,
)
from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import TraceStatus
from runtime.run_trace import TraceRecorder
from runtime.security.S18_2_injection_guard import (
    InjectionGuard,
)
from runtime.security.S18_3_no_evidence import (
    NoEvidencePolicy,
    build_abstention_answer,
)


# 二、两个安全能力处理器

# #### 内部执行流程
# 1. **参数提取与校验**
#    - 提取 `run_id`、输入来源类型、直接文本、文档列表
#    - 校验：文档必须是列表格式；必须有文本或文档内容，否则抛错

# 2. **合并检测文本**
# combined = "\n".join([text, *[str(item) for item in documents]]).strip()
# 把用户直接输入的文本 + 所有检索文档的内容拼接起来，统一做检测，覆盖两种注入路径。

# 3. **调用注入检测器**
# guard = InjectionGuard()
# detection = guard.detect(combined)
# 调用底层注入防护原语，输出检测结果：是否命中、攻击类别、匹配的模式。

# 4. **记录安全事件**
#    - 检测到注入 → 状态 `REJECTED`，动作 `blocked_or_marked`
#    - 未检测到 → 状态 `SUCCEEDED`，动作 `allowed`
#    - 元数据带上来源类型、是否命中、攻击分类、匹配的具体模式

# 5. **返回结构化结果**
#    - 状态：`blocked` / `allowed`
#    - 检测详情：是否命中、类别、匹配模式
#    - 处置动作：命中则标记为不可信内容
#    - 清理后的文本：调用 `sanitize()` 输出净化后的文本

# #### 设计价值
# - 同时覆盖「用户直接输入注入」和「检索文档带注入」两种场景，对应真实 RAG 系统的两大注入风险点
# - 完整的安全审计留痕，所有拦截事件可追溯、可统计
# - 可以通过接口快速测试不同攻击样本的拦截效果，验证防护规则的有效性

### 1. `security_injection_handler` —— 提示注入防护能力
# **对应底层原语**：`InjectionGuard`（注入检测 + 清理）
# **定位**：检测用户输入、检索文档中的提示注入攻击，覆盖「直接输入注入」和「文档间接注入」两种场景。
def security_injection_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or "cap-security-injection"
    )
    source_type = str(
        payload.input.get(
            "source_type",
            "direct",
        )
    )
    text = str(
        payload.input.get(
            "text",
            "",
        )
    )
    documents = payload.input.get(
        "documents",
        [],
    )

    if not isinstance(documents, list):
        raise ValueError(
            "documents must be a list"
        )

    combined = "\n".join(
        [
            text,
            *[
                str(item)
                for item in documents
            ],
        ]
    ).strip()

    if not combined:
        raise ValueError(
            "text or documents is required"
        )

    guard = InjectionGuard()
    detection = guard.detect(combined)

    status = (
        TraceStatus.REJECTED
        if detection.detected
        else TraceStatus.SUCCEEDED
    )

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:security:injection"
            ),
            run_id=run_id,
            stage="security",
            operation="security_injection",
            status=status,
            action=(
                "blocked_or_marked"
                if detection.detected
                else "allowed"
            ),
            metadata={
                "source_type": source_type,
                "detected": detection.detected,
                "category": (
                    detection.category
                ),
                "matched_pattern": (
                    detection.matched_pattern
                ),
            },
        )
    )

    return {
        "status": (
            "blocked"
            if detection.detected
            else "allowed"
        ),
        "source_type": source_type,
        "detected": detection.detected,
        "category": detection.category,
        "matched_pattern": (
            detection.matched_pattern
        ),
        "action": (
            "untrusted_content"
            if detection.detected
            else "none"
        ),
        "sanitized_text": (
            guard.sanitize(combined)
        ),
    }


#### 内部执行流程

# 1. **参数提取与校验**
#    - 提取用户问题、检索上下文列表、最小证据数量阈值、最低相关性分数阈值
#    - 校验：问题必填；检索上下文必须是列表格式

# 2. **创建评估策略**
# policy = NoEvidencePolicy(
#     min_evidence_count=min_evidence_count,
#     min_score=min_score,
# 配置评估规则：最少需要几条证据、最低相关性分数多少才算证据充足。

# 3. **证据充足性评估**
# assessment = policy.assess(question=question, retrieval_context=retrieval_context)
# 调用底层策略评估，输出：是否有足够证据、拒绝原因、实际证据数、最高相关性分数。

# 4. **生成对应回答**
# answer = build_abstention_answer(assessment=assessment, question=question)
#    - 证据充足：返回允许生成的标识
#    - 证据不足：生成标准的「资料不足无法回答」拒答话术

# 5. **记录安全事件**
#    - 证据充足 → 状态 `SUCCEEDED`，动作 `allow_generation`
#    - 证据不足 → 状态 `REJECTED`，动作 `abstain`
#    - 元数据带上是否有证据、拒绝原因、证据数量、最高分数

# 6. **返回结构化结果**
#    - 状态：`evidence_found` / `no_evidence`
#    - 评估详情：有没有证据、原因、证据数、最高分
#    - 生成的回答：对应允许生成或标准拒答

### 2. `security_no_evidence_handler` —— 无证据拒答能力

# **对应底层原语**：`NoEvidencePolicy`（证据充足性评估） + `build_abstention_answer`（标准拒答话术生成）
# **定位**：评估检索证据是否足够支撑回答，证据不足时输出标准拒答话术，避免大模型幻觉编造。
def security_no_evidence_handler(
    payload: CapabilityRunRequest,
    recorder: TraceRecorder,
) -> dict[str, Any]:
    run_id = (
        payload.run_id
        or "cap-security-no-evidence"
    )
    question = str(
        payload.input.get(
            "question",
            "",
        )
    ).strip()

    if not question:
        raise ValueError(
            "input.question is required"
        )

    retrieval_context = (
        payload.input.get(
            "retrieval_context",
            [],
        )
    )

    if not isinstance(
        retrieval_context,
        list,
    ):
        raise ValueError(
            "retrieval_context must be a list"
        )

    min_evidence_count = int(
        payload.input.get(
            "min_evidence_count",
            1,
        )
    )

    raw_min_score = payload.input.get(
        "min_score"
    )
    min_score = (
        None
        if raw_min_score is None
        else float(raw_min_score)
    )

    policy = NoEvidencePolicy(
        min_evidence_count=(
            min_evidence_count
        ),
        min_score=min_score,
    )
    assessment = policy.assess(
        question=question,
        retrieval_context=(
            retrieval_context
        ),
    )
    answer = build_abstention_answer(
        assessment=assessment,
        question=question,
    )

    recorder.append(
        CapabilityEvent(
            event_id=(
                f"{run_id}:security:no-evidence"
            ),
            run_id=run_id,
            stage="security",
            operation="security_no_evidence",
            status=(
                TraceStatus.SUCCEEDED
                if assessment.has_evidence
                else TraceStatus.REJECTED
            ),
            action=(
                "allow_generation"
                if assessment.has_evidence
                else "abstain"
            ),
            metadata={
                "has_evidence": (
                    assessment.has_evidence
                ),
                "reason": assessment.reason,
                "evidence_count": (
                    assessment.evidence_count
                ),
                "best_score": (
                    assessment.best_score
                ),
            },
        )
    )

    return {
        "status": (
            "evidence_found"
            if assessment.has_evidence
            else "no_evidence"
        ),
        "has_evidence": (
            assessment.has_evidence
        ),
        "reason": assessment.reason,
        "evidence_count": (
            assessment.evidence_count
        ),
        "best_score": (
            assessment.best_score
        ),
        "answer": answer,
    }




# 三、能力注册函数
def register_security_capabilities(
    registry: CapabilityRegistry,
) -> None:
    if registry.has("security_injection"):
        return

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id=(
                    "security_injection"
                ),
                name="Prompt Injection Guard",
                description=(
                    "Detect direct and indirect "
                    "prompt injection."
                ),
                category="security",
                tags=[
                    "injection",
                    "guard",
                ],
            ),
            handler=security_injection_handler,
        )
    )

    registry.register(
        CapabilityDefinition(
            descriptor=CapabilityDescriptor(
                capability_id=(
                    "security_no_evidence"
                ),
                name="No Evidence Guard",
                description=(
                    "Abstain when retrieval "
                    "evidence is insufficient."
                ),
                category="security",
                tags=[
                    "abstention",
                    "evidence",
                ],
            ),
            handler=(
                security_no_evidence_handler
            ),
        )
    )

