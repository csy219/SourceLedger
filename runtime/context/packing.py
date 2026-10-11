# 这是 **B06 阶段的上下文打包适配器**，采用**适配器模式**桥接新版标准契约和已有的成熟上下文打包逻辑，把检索 / 重排后的候选文档，按照 Token 预算裁剪、去重、组装成可直接输入大模型的标准上下文包，同时输出结构化的证据、引用、冲突、安全检测结果。

# 核心设计思路：复用已经验证过的旧版上下文打包算法，只做格式转换和契约封装，不重复造轮子，同时对外输出完全符合 B01 标准的 `ContextPack` 契约。
## 一、整体定位

# - **输入**：检索 / 重排后的 `RetrievalCandidate` 列表、Token 预算参数
# - **输出**：标准 `ContextPack` 契约（可直接传给生成模块）
# - **核心依赖**：旧版已验证的 `legacy_pack_context` 函数，负责实际的裁剪、去重、拼接逻辑
# - **模式**：适配器（Adapter）模式，新老系统无缝对接

"""Production adapter for SourceLedger context packing."""

from __future__ import annotations

from typing import Any

from evaluation.S13_2_context_packer import (
    pack_context as legacy_pack_context,
)
from runtime.rag_contracts import (
    CitationContract,
    ConflictInfo,
    ContentType,
    ContextPack,
    EvidenceItem,
    InjectionFinding,
    RetrievalCandidate,
    TrustLevel,
)


# 1. `_candidate_to_legacy_dict` —— 新契约转旧格式
# **作用**：把新版标准 `RetrievalCandidate` 对象，转换成旧版打包函数能识别的字典格式。
# 字段处理	说明
# payload = dict(candidate.metadata)	先把元数据展开作为基础字段
# 双 ID 兼容	同时填 child_id 和 chunk_id，兼容旧版不同字段名的逻辑
# 全量排名 / 分数	把向量、BM25、RRF、重排四路的排名和分数全部传入，旧逻辑可以按需使用
# input_rank	输入的原始排序序号，旧版逻辑用来做优先级判断
def _candidate_to_legacy_dict(candidate: RetrievalCandidate, input_rank: int) -> dict[str, Any]:
    payload = dict(candidate.metadata)
    payload.update({
        "child_id": candidate.chunk_id,
        "chunk_id": candidate.chunk_id,
        "source": candidate.source,
        "page": candidate.page,
        "text": candidate.text,
        "input_rank": input_rank,
        "vector_rank": candidate.vector_rank,
        "vector_score": candidate.vector_score,
        "bm25_rank": candidate.bm25_rank,
        "bm25_score": candidate.bm25_score,
        "rrf_rank": candidate.rrf_rank,
        "rrf_score": candidate.rrf_score,
        "rerank_rank": candidate.rerank_rank,
        "rerank_score": candidate.rerank_score,
    })
    return payload

# 2. `_best_score` —— 取最优相关性得分
# **作用**：按优先级取当前候选的**最高级别相关性得分**，作为证据项的最终得分。
# **优先级顺序**：重排得分 > RRF 融合得分 > 向量得分 > BM25 得分
# - 做过重排就用重排分（最精准）
# - 没重排就用 RRF 融合分
# - 单路检索就用对应路的得分
# - 都没有返回 0.0
# > 设计意图：统一证据得分口径，不管走了哪几步检索，都能拿到当前最准确的相关性评分。
def _best_score(candidate: dict[str, Any]) -> float:
    for key in ("rerank_score", "rrf_score", "vector_score", "bm25_score"):
        value = candidate.get(key)
        if value is not None:
            return float(value)
    return 0.0

# 3. `_build_conflict` —— 冲突信息格式转换
# **作用**：把旧版输出的冲突字典，转换成标准 `ConflictInfo` 契约对象。
# 逻辑	说明
# 无冲突 / 来源不足 2 个	返回空元组，不生成冲突记录
# 有冲突	构造标准冲突信息：
# ・主题为文档基础名
# ・两个冲突来源
# ・固定差异说明
# ・标记为必须向用户披露
def _build_conflict(conflict: dict[str, Any]) -> tuple[ConflictInfo, ...]:
    if not conflict.get("has_conflict"):
        return ()
    sources = [str(source) for source in (conflict.get("sources") or [])]
    if len(sources) < 2:
        return ()
    return (ConflictInfo(
        topic=str(conflict.get("base_name", "")),
        source_a=sources[0],
        source_b=sources[1],
        differences=("检测到同一文档的不同版本，回答必须披露版本差异。",),
        requires_disclosure=True,
    ),)

# 四、主函数 `pack_runtime_context`
# 这是模块对外的核心接口，输入候选列表和预算参数，输出标准 `ContextPack`。
# 参数	作用
# candidates	检索 / 重排后的候选文档列表
# retrieval_budget	检索部分的 Token 预算上限，上下文不能超过这个数
# max_chunk_per_page	单页最多选几个片段，避免同一页内容重复过多
# max_chunk_per_parent	单个父文档最多选几个片段，避免结果被单一文档霸榜
def pack_runtime_context(
    candidates: list[RetrievalCandidate] | tuple[RetrievalCandidate, ...],
    retrieval_budget: int = 1800,
    max_chunk_per_page: int = 2,
    max_chunk_per_parent: int = 2,
) -> ContextPack:
    # ① 格式转换 + 调用旧版打包
    # 1. 把所有新版候选统一转换成旧版字典格式
    # 2. 调用旧版核心打包逻辑，完成实际工作：
    # - 按相关性优先级筛选
    # - 每页 / 每文档数量限制
    # - 重复内容去重
    # - 按 Token 预算截断
    # - 生成带 `[1]` `[2]` 引用标记的上下文文本
    # - 输出选中条目、统计信息、冲突检测结果
    legacy_candidates = [
        _candidate_to_legacy_dict(candidate, input_rank=index)
        for index, candidate in enumerate(candidates, start=1)
    ]
    packed = legacy_pack_context(
        candidates=legacy_candidates,
        retrieval_budget=retrieval_budget,
        max_chunk_per_page=max_chunk_per_page,
        max_chunk_per_parent=max_chunk_per_parent,
    )

    # ② 初始化输出容器
    # - `retrieval_context`：旧版输出的最终选中的上下文条目列表
    # - 三个列表分别存放标准契约对象：证据、引用、注入检测结果
    retrieval_context = list(packed["retrieval_context"])
    evidence: list[EvidenceItem] = []
    citations: list[CitationContract] = []
    injections: list[InjectionFinding] = []

    # ③ 遍历选中条目，组装标准契约
    # - 按顺序生成证据 ID（`E1`、`E2`...）
    # - 取出旧版生成的引用编号
    # - 兼容两种 chunk 字段名，兜底用证据 ID
    # - 读取可疑指令标记
    for index,item in enumerate(retrieval_context,start=1):
        evidence_id=f"E{index}"
        citation_id=str(item.get("citation_id"))
        chunk_id=str(item.get("child_id") or item.get("chunk_id") or evidence_id)
        suspicious = bool(item.get("suspicious_instruction", False))

        # 构造证据项
        # - 所有字段对齐标准 `EvidenceItem` 契约
        # - 得分调用 `_best_score` 取最优值
        # - 默认信任等级为 `UNTRUSTED`（未做可信校验前默认不可信）
        # - 元数据保留所有阶段的排名，可追溯
        evidence.append(EvidenceItem(
            evidence_id=evidence_id,
            chunk_id=chunk_id,
            source=str(item["source"]),
            page=int(item["page"]),
            text=str(item["text"]),
            score=_best_score(item),
            trust_level=TrustLevel.UNTRUSTED,
            suspicious_instruction=suspicious,
            content_type=ContentType.RETRIEVED_DOCUMENT,
            metadata={
                "vector_rank": item.get("vector_rank"),
                "bm25_rank": item.get("bm25_rank"),
                "rrf_rank": item.get("rrf_rank"),
                "rerank_rank": item.get("rerank_rank"),
            },
        ))

        # 构造引用项
        # - 建立「引用编号 → 证据 ID」的映射关系
        # - 前端点击引用编号时，可通过 evidence_id 定位完整证据
        citations.append(CitationContract(
            citation_id=citation_id,
            evidence_id=evidence_id,
            source=str(item["source"]),
            page=int(item["page"]),
        ))

        # 可疑指令生成注入记录
        # - 检测到可疑指令时，生成标准 `InjectionFinding` 记录
        # - 标记为高严重度，动作为「标记为不可信内容」
        # - 截取前 160 字符作为可疑片段
        if suspicious:
            injections.append(InjectionFinding(
                finding_id=f"I{index}",
                chunk_id=chunk_id,
                severity="high",
                matched_pattern="suspicious_instruction_pattern",
                action="untrusted_content",
                excerpt=str(item["text"])[:160],
            ))
    # ④ 统计指标计算
    # - 取出旧版输出的统计数据
    # - 计算**来源多样性**：唯一来源数 / 选中证据总数，值越高说明来源越分散，回答越全面
    stats = dict(packed.get("stats") or {})
    selected_count = len(evidence)
    unique_sources = int(stats.get("unique_sources", 0) or 0)
    source_diversity = unique_sources / selected_count if selected_count else 0.0


    # ⑤ 组装标准 ContextPack 返回
    # 字段	说明
    # context_text	拼接好的带引用标记的完整上下文文本，可直接喂给大模型
    # evidence	所有选中的证据项，结构化可追溯
    # citations	引用编号和证据的映射关系
    # conflicts	检测到的文档版本冲突
    # injections	检测到的可疑注入内容
    # context_tokens	上下文实际 Token 数
    # budget_used	实际使用的预算
    # duplicate_text_count	去重的重复片段数量
    # source_diversity	来源多样性得分
    # metadata	原始统计数据透传，方便调试
    return ContextPack(
        context_text=str(packed.get("context_text", "")),
        evidence=tuple(evidence),
        citations=tuple(citations),
        conflicts=_build_conflict(dict(packed.get("conflict") or {})),
        injections=tuple(injections),
        context_tokens=int(stats.get("retrieval_tokens", 0) or 0),
        budget_used=int(stats.get("retrieval_tokens", 0) or 0),
        duplicate_text_count=int(stats.get("duplicate_text_count", 0) or 0),
        source_diversity=round(source_diversity, 4),
        metadata={"context_stats": stats},
    )

## 五、核心设计特点

# 1. **适配器模式，风险最低**：复用已验证的旧版核心逻辑，只做格式转换和契约封装，不用重写算法，稳定性有保障。
# 2. **信息完全透传**：所有排名、分数、元数据完整传递，不丢失任何过程信息，可追溯、可对比。
# 3. **标准契约输出**：对外完全输出 B01 定义的标准结构，上下游完全解耦，内部替换实现不影响外部。
# 4. **安全能力内置**：可疑指令自动转换成标准注入检测记录，安全特性不是外挂，是上下文的原生属性。
# 5. **统计指标完备**：Token 用量、去重数量、来源多样性都有量化指标，方便效果评估和参数调优。


# 六、在整条链路中的位置
# 检索/重排候选列表
#           ↓
# pack_runtime_context 上下文打包
#           ↓
# 标准 ContextPack
#           ↓
# B07 大模型生成回答
# 上下文打包是检索和生成之间的最后一步，负责把原始候选加工成符合预算、带引用、去重后的高质量上下文，直接决定生成回答的质量和准确性。

