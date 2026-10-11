# 进入 B05-1：实现全局、懒加载、无副作用的 Reranker。
# 现有 S12_2_reranker_adapter.py 有两个问题，不适合生产：
# 1. 构造对象时就加载模型，无法做到条件触发。
# 2. 直接修改传入的字典，容易污染 RRF 候选。
# 所以生产模块会改成：
# 默认不加载
# 满足条件才加载
# 返回新 RetrievalCandidate
# 不修改 RRF 原始结果


# 这是 **B05 阶段的条件式 CrossEncoder 重排模块**，是混合检索链路的「质量优化层」。
# 核心设计思想是**按需触发、优雅降级**：重排模型计算成本高、速度慢，不默认全程开启，只在「结果区分度低、查询有歧义、用户明确要求」等场景下才启动，用 CrossEncoder 做更精准的语义相关性打分重排序，提升顶部结果的准确率；不需要时直接沿用 RRF 结果，兼顾检索效果和整体性能。


"""Conditional CrossEncoder reranking."""

from __future__ import annotations

import time
from dataclasses import (
    dataclass,
    replace,
)
from typing import Any

from runtime.rag_contracts import (
    RetrievalCandidate,
)

PRIMARY_MODEL = "BAAI/bge-reranker-v2-m3"
FALLBACK_MODEL = "BAAI/bge-reranker-base"

# RerankerConfig 重排配置类
# 参数	作用
# primary_model / fallback_model	主 / 备选模型名称
# device	运行设备，默认 cpu，兼容无 GPU 环境
# max_length	单条文本最大长度，超过截断，控制计算量
# batch_size	批量预测的批次大小，平衡速度和内存
# candidate_threshold	触发重排的候选数量阈值，候选超过这个数才重排
# score_margin_threshold	RRF 前两名分差阈值，分差小于这个值说明区分度低，触发重排
# allow_fallback	是否允许模型加载失败时降级到 RRF 排序
@dataclass(frozen=True)
class RerankerConfig:
    primary_model: str = PRIMARY_MODEL
    fallback_model: str = FALLBACK_MODEL
    device: str = "cpu"
    max_length: int = 512
    batch_size: int = 8
    candidate_threshold: int = 30
    score_margin_threshold: float = 0.002
    allow_fallback: bool = True


# 字段	作用
# candidates	重排后的候选列表，标准 RetrievalCandidate 结构，新增 rerank_rank/rerank_score
# triggered	是否实际执行了重排
# skipped_reason	跳过重排的原因，用于调试
# backend	运行后端：cross_encoder / injected / noop
# model_name	实际使用的模型名
# load_ms	模型加载耗时，用于性能分析
# latency_ms	重排总耗时
# error	错误信息，加载失败时记录
@dataclass
class RerankResult:
    candidates: tuple[
        RetrievalCandidate,
        ...,
    ]
    triggered: bool
    skipped_reason: str
    backend: str
    model_name: str
    load_ms: float
    latency_ms: float
    error: str = ""

# 二、`should_rerank` 触发判断函数
# 这是**条件重排的核心逻辑**，判断当前场景要不要启动重排模型，满足任意一条就触发，都不满足就跳过。
def should_rerank(
    candidates: (
        list[RetrievalCandidate]
        | tuple[RetrievalCandidate, ...]
    ),
    allow_rerank: bool,
    query_ambiguous: bool,
    config: RerankerConfig,
) -> tuple[bool, str]:
    if allow_rerank:
        return True, "request_allow_rerank"

    if query_ambiguous:
        return True, "query_ambiguous"

    if (
        len(candidates)
        >= config.candidate_threshold
    ):
        return (
            True,
            "candidate_threshold",
        )

    if len(candidates) >= 2:
        top_1 = (
            candidates[0].rrf_score
            or 0.0
        )
        top_2 = (
            candidates[1].rrf_score
            or 0.0
        )
        margin = abs(
            float(top_1) - float(top_2)
        )

        if (
            margin
            <= config.score_margin_threshold
        ):
            return True, "small_rrf_margin"

    return False, "conditions_not_met"

class Reranker:
    def __init__(
        self,
        config:RerankerConfig | None = None,
        model:Any | None =None,
    )->None:
        # 成员	作用
        # config	配置对象，默认用标准配置
        # model	支持外部注入模型，方便单元测试 Mock
        # backend	后端状态：injected（外部注入）/ not_loaded（未加载）/ cross_encoder（正常加载）/ noop（加载失败）
        # load_ms / load_error	模型加载耗时和错误信息，懒加载后填充
        self.config=(
            config
            if config is not None
            else RerankerConfig()
        )

        self.model=model
        self.model_name=self.config.primary_model
        self.backend=(
            "injected"
            if model is not None
            else
            "not_loaded"
        )
        self.load_ms=0.0
        self.load_error=""

    # 2. `_try_load` 内部加载模型
    # - 内部导入 `sentence_transformers` 的 `CrossEncoder`，避免顶层强制依赖
    # - 按配置加载指定模型，返回模型实例
    def _try_load(
        self,
        model_name:str
    )->Any:
        from sentence_transformers import  CrossEncoder

        return CrossEncoder(
            model_name,
            device=self.config.device,
            max_length=self.config.max_length
        )

    # 3. `load_model` 模型加载与降级
    # 设计：**优雅降级**。主模型挂了试备选，都挂了也不报错，后面自动退回 RRF 排序，链路不中断。
    def load_model(self)->None:
        if self.model is not None:
            return

        # 已经加载过就直接返回，保证只加载一次。
        started=time.perf_counter()
        candidates=[self.config.primary_model]
        if self.config.allow_fallback and self.config.fallback_model not in candidates:
            candidates.append(self.config.fallback_model)

        # 组装加载候选列表：先主模型，允许降级的话加上备选模型。
        # 按顺序尝试加载模型，成功就停止；失败就记录错误，继续试下一个
        errors:list[str]=[]
        for model_name in candidates:
            try:
                self.model=self._try_load(model_name)
                self.model_name=model_name
                self.backend="cross_encoder"
                break
            except Exception as exc:
                errors.append(f"{model_name}:{type(exc).__name__}:{exc}")

        # - 记录加载耗时
        self.load_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        # - 全部失败就标记后端为 `noop`，记录错误信息
        if self.model is None:
            self.backend = "noop"
            self.load_error = " | ".join(
                errors
            )
    # 4. `_fallback_order` 降级排序
    @staticmethod
    def _fallback_order(
        candidates: (
            list[RetrievalCandidate]
            | tuple[
                RetrievalCandidate,
                ...,
            ]
        ),
        top_k: int,
    ) -> tuple[
        RetrievalCandidate,
        ...,
    ]:
        ordered = sorted(
            candidates,
            key=lambda item: (
                -(
                    item.rrf_score
                    or 0.0
                ),
                item.chunk_id,
            ),
        )

        return tuple(
            replace(
                candidate,
                rerank_rank=rank,
                rerank_score=round(
                    candidate.rrf_score
                    or 0.0,
                    8,
                ),
            )
            for rank, candidate in enumerate(
                ordered[:top_k],
                start=1,
            )
        )

    # 5. `rerank` 核心重排方法
    def rerank(
        self,
        question: str,
        candidates: (
            list[RetrievalCandidate]
            | tuple[
                RetrievalCandidate,
                ...,
            ]
        ),
        top_k: int,
    ) -> RerankResult:
        started=time.perf_counter()

        # ① 空候选快速返回
        if not candidates:
            return RerankResult(
                candidates=(),
                triggered=True,
                skipped_reason="",
                backend=self.backend,
                model_name=self.model_name,
                load_ms=self.load_ms,
                latency_ms=0.0,
            )
        # ② 懒加载模型
        # 第一次调用才加载模型，加载过就复用。
        self.load_model()

        # ③ 模型加载失败，降级处理
        if self.model is None:
            latency_ms=round((time.perf_counter()-started)*1000,2)
            return RerankResult(
                candidates=(
                    self._fallback_order(
                        candidates,
                        top_k,
                    )
                ),
                triggered=True,
                skipped_reason="",
                backend=self.backend,
                model_name=self.model_name,
                load_ms=self.load_ms,
                latency_ms=latency_ms,
                error=self.load_error,
            )
        # ④ 构造查询 - 文档对
        # CrossEncoder 的输入格式是「(查询，文档)」对，模型输出两者的语义相关性得分。
        pairs=[(question,candidate.text)for candidate in candidates]

        # ⑤ 批量预测得分
        # 调用 CrossEncoder 批量预测，得到每个候选和查询的相关性得分。
        scores=self.model.predict(
            pairs,
            batch_size=self.config.batch_size,
            show_progress_bar=False
        )
        # ⑥ 填充得分并排序
        # - 给每个候选填充 `rerank_score`
        # - 排序规则：主排序按重排得分降序；重排得分相同时，按 RRF 得分降序；再相同按 chunk_id 稳定排序。
        scored=[
            replace(candidate,rerank_score=round(float(score),8))
            for candidate,score in zip(candidates,scores)
        ]
        scored.sort(
            key=lambda item: (
                -(item.rerank_score or 0.0),
                -(item.rrf_score or 0.0),
                item.chunk_id,
            )
        )

        # ⑦ 填充排名并返回
        reranked = tuple(
            replace(
                candidate,
                rerank_rank=rank,
            )
            for rank, candidate in enumerate(
                scored[:top_k],
                start=1,
            )
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        return RerankResult(
            candidates=reranked,
            triggered=True,
            skipped_reason="",
            backend=self.backend,
            model_name=self.model_name,
            load_ms=self.load_ms,
            latency_ms=latency_ms,
            error=self.load_error,
        )

        
    

        