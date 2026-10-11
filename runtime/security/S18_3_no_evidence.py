from dataclasses import dataclass
from typing import Any

# 2. EvidenceAssessment 评估结果数据类
@dataclass(frozen=True)
class EvidenceAssessment:

    # - `has_evidence: bool`：布尔标记，`True`代表证据充足可以回答，`False`代表证据不足应当拒答。
    # - `reason: str`：评估结果的原因编码，是固定枚举式字符串（如`no_retrieval_results`），用于日志记录、问题排查和后续流程分支判断。
    # - `evidence_count: int`：实际可用的有效证据（检索文档）数量。
    # - `best_score: float | None`：所有有效证据中的最高质量分，分数越高代表证据和问题的相关性越强；无有效分数时为`None`。
    has_evidence:bool
    reason:str
    evidence_count:int
    best_score:float | None

# 3. NoEvidencePolicy 核心评估策略类
class NoEvidencePolicy:
    def __init__(
        self,
        min_evidence_count:int=1,
        min_score:float | None=None,
    )->None:
        self.min_evidence_count=min_evidence_count
        self.min_score=min_score

    # - 作用：执行完整的证据充足性分层校验，输入用户问题和检索上下文列表，输出标准化评估结果。
    # - `question: str`：入参，用户提问文本（当前版本未直接参与计算，预留用于后续语义相关性校验扩展）。
    # - `retrieval_context: list[dict[str, Any]]`：入参，检索器返回的上下文文档列表，每个元素是包含文本、分数等字段的字典。
    def assess(
        self,
        question:str,
        retrieval_context:list[dict[str,Any]],
    )->EvidenceAssessment:
        if not retrieval_context:
            return EvidenceAssessment(
                has_evidence=False,
                reason="no_retrieval_results",
                evidence_count=0,
                best_score=None,
            )

        # 第二层：有效证据过滤与数量校验
        # - 判断有效证据数量是否小于配置的最小阈值；
        # - 不足则返回无证据结果，原因编码为`insufficient_evidence_count`（证据数量不足），同时返回实际有效证据数量。
        usable=[
            item
            for item in retrieval_context
            if str(item.get("text","")).strip()
        ]
        if len(usable) < self.min_evidence_count:
            return EvidenceAssessment(
                has_evidence=False,
                reason="insufficient_evidence_count",
                evidence_count=len(usable),
                best_score=None,
            )

        # 第三层：证据质量打分与最高分计算
        # **变量`scores`**：所有有效证据的分数列表，遍历每个有效文档，调用私有方法`_score`提取 / 计算质量分数。
        scores=[
            self._score(item)
            for item in usable
        ]
        # 过滤掉分数为`None`的项（即没有任何可识别分数字段的文档），避免后续`max`计算报错
        scores=[
            score
            for score in scores
            if score is not None
        ]
        # **变量`best_score`**：所有有效分数中的最大值，代表相关性最高的证据的质量；如果过滤后没有有效分数，则为`None`。
        best_score=(
            max(scores)
            if scores
            else None
        )

        # 第四层：分数阈值校验
        # - 同时满足三个条件才触发校验失败：
        # 1. 配置了最小分数阈值（`min_score`不为 None）；
        # 2. 存在有效最高分（`best_score`不为 None）；
        # 3. 最高分低于配置的阈值；
        # - 失败则返回无证据结果，原因编码为`score_below_threshold`（分数低于阈值）。
        if(
            self.min_score is not None
            and best_score is not None
            and best_score<self.min_score
        ):
            return EvidenceAssessment(
                has_evidence=False,
                reason="score_below_threshold",
                evidence_count=len(usable),
                best_score=best_score,
            )
        # 最终：所有校验通过
        return EvidenceAssessment(
            has_evidence=True,
            reason="evidence_found",
            evidence_count=len(usable),
            best_score=best_score,
        )

    # 3.3 _score 私有打分方法
    def _score(
        self,
        item: dict[str, Any],
    ) -> float | None:
        if item.get("score") is not None:
            return float(item["score"])

        if item.get("rrf_score") is not None:
            return float(item["rrf_score"])

        if item.get("similarity") is not None:
            return float(item["similarity"])

        if item.get("distance") is not None:
            return 1.0 - float(
                item["distance"]
            )

        return None
        
# 4. build_abstention_answer 拒答话术生成函数
# - 作用：根据评估结果生成对应的回复文本，可直接返回给用户，或者作为提示词指导大模型生成回答。
# - `assessment: EvidenceAssessment`：入参，证据评估结果对象。
# - `question: str`：入参，用户原问题（当前版本未直接使用，预留用于生成个性化拒答话术）
def build_abstention_answer(
    assessment: EvidenceAssessment,
    question: str,
) -> str:
    if assessment.has_evidence:
        return (
            "资料中找到 "
            f"{assessment.evidence_count} 条证据，"
            "可以继续生成回答。"
        )

    return (
        "资料中没有足够信息回答该问题，"
        "不能进行推测或编造。"
    )

        
### 三、核心设计总结

# 1. **分层校验机制**：按照「空结果→数量不足→质量不足」的顺序分层校验，提前拦截无效场景，兼顾性能和逻辑清晰度。
# 2. **高兼容性**：`_score`方法兼容 4 种常见的检索分数字段，可适配向量检索、关键词检索、多路融合等多种检索架构。
# 3. **可配置策略**：通过`min_evidence_count`和`min_score`两个阈值，可灵活调整评估的严格程度，适配不同业务场景的容错要求。
# 4. **结构化结果**：评估结果包含明确的原因编码，便于日志排查、问题定位和后续流程分支控制。