"""SourceLedger RAG Runtime contracts.

This module contains data contracts only. It must not import Chroma,
BM25, LangGraph, or any model SDK.
"""
### 二、你必须掌握的部分（会用就够）

# 这几点是后续开发天天要用的，必须记牢：

# 1. **所有业务数据契约，都必须继承`ContractModel`**
# 继承后自动获得`to_dict()`、`to_json()`、`from_dict()`、`from_json()`四个标准方法，这是跨模块传参、接口返回、日志存储的基础。
# 2. **所有状态、类型、错误码，必须用这里的枚举**
# 禁止在业务代码里写裸字符串（比如`"success"`、`"vector"`），统一用`RAGStatus.SUCCEEDED`、`RetrievalMode.VECTOR`这种枚举值，从根源避免拼写错误。
# 3. **`_require()`是通用字段校验工具**
# 后面写契约校验逻辑（比如 “查询不能为空”“分数必须在 0~1 之间”）可以直接复用它，不用自己写`if + raise`。
# 4. **这个文件是纯数据层，绝对不能引入业务依赖**
# 记住这条铁律：`rag_contracts.py`里永远不能导入 Chroma、LangGraph、模型 SDK、FastAPI 这些东西，保持零依赖，否则就失去了契约解耦的意义。
from __future__ import annotations

import json
import types
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints


### 五、总结一下你需要记住的边界

# 1. `ContractModel` 是给后面业务类继承的，现在只是先把底座造好，后面才会用到。
# 2. 序列化 = 对象转 JSON（发出去、存起来），反序列化 = JSON 转对象（收进来、用起来）。
# 3. 这套代码的核心价值是：**类型无损**，转出去再转回来，类型和结构和原来一模一样。
# 4. 你不用抠 `_decode` 里的每一行判断，只要知道 “它能正确还原类型” 就行，出问题再回来查。





#### 1. `utc_now()`
# 统一生成 UTC 时区的 ISO 格式时间字符串。
# → 后面所有契约里的时间字段（请求时间、检索时间、生成时间）都用它生成，避免各模块用本地时间、格式不一导致时序混乱。
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


#### 2. `_require(condition, message)`
# 统一的校验工具。
# → 后面写业务契约的时候，比如要求 `score` 必须在 0~1 之间、`query` 不能为空，都可以用它校验，不用每个地方都写 `if + raise`，错误信息格式统一。
def _require(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise ValueError(message)


#### 3. `_to_primitive(value)` —— 序列化核心

# 递归遍历整个对象，把所有 Python 高级类型（枚举、dataclass、元组、集合）都转成 JSON 能识别的原生类型（字符串、字典、列表）。
# → 上面例子里，把 `RetrievalMode.VECTOR` 转成 `"vector"`，把整个 dataclass 转成字典，都是它在干活。
def _to_primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value) and not isinstance(
        value,
        type,
    ):
        return {
            item.name: _to_primitive(
                getattr(value, item.name)
            )
            for item in fields(value)
        }

    if isinstance(value, dict):
        return {
            str(key): _to_primitive(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (list, tuple, set, frozenset),
    ):
        return [
            _to_primitive(item)
            for item in value
        ]

    return value


#### 4. `_decode(value, target_type)` —— 反序列化核心

# 反向遍历数据，根据目标类型，把原生值还原回枚举、嵌套 dataclass、泛型列表等高级类型。
# → 上面例子里，把 `"vector"` 还原回 `RetrievalMode.VECTOR` 枚举，把整个字典还原成 `RetrievedDocument` 对象，都是它在干活。
# 它还支持 Union、可选字段、嵌套结构，是整个底座里最复杂的部分。
def _decode(
    value: Any,
    target_type: Any,
) -> Any:
    if value is None:
        return None

    if target_type is Any:
        return value

    origin = get_origin(target_type)
    args = get_args(target_type)

    if origin in (
        types.UnionType,
        typing.Union,
    ):
        for option in args:
            if option is type(None):
                continue

            try:
                return _decode(value, option)
            except (TypeError, ValueError):
                continue

        return value

    if origin in (
        list,
        tuple,
        set,
        frozenset,
    ):
        item_type = (
            args[0]
            if args
            else Any
        )
        decoded = [
            _decode(item, item_type)
            for item in value
        ]

        if origin is tuple:
            return tuple(decoded)
        if origin is set:
            return set(decoded)
        if origin is frozenset:
            return frozenset(decoded)

        return decoded

    if origin is dict:
        key_type = (
            args[0]
            if args
            else Any
        )
        value_type = (
            args[1]
            if len(args) > 1
            else Any
        )

        return {
            _decode(key, key_type): _decode(
                item,
                value_type,
            )
            for key, item in value.items()
        }

    if isinstance(target_type, type):
        if issubclass(target_type, Enum):
            return target_type(value)

        if is_dataclass(target_type):
            hints = get_type_hints(target_type)

            kwargs = {
                item.name: _decode(
                    value[item.name],
                    hints.get(
                        item.name,
                        Any,
                    ),
                )
                for item in fields(target_type)
                if item.name in value
            }

            return target_type(**kwargs)

    return value

#### 5. `ContractModel` 基类

# 把上面两个核心函数包装成 4 个标准方法：`to_dict()`、`to_json()`、`from_dict()`、`from_json()`。
# → 所有业务契约只要继承它，一键获得完整的序列化能力，不用重复写代码，而且所有类的序列化行为完全一致。
class ContractModel:
    def to_dict(self) -> dict[str, Any]:
        payload = _to_primitive(self)

        if not isinstance(payload, dict):
            raise TypeError(
                "Contract root must serialize to an object"
            )

        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> Any:
        return _decode(payload, cls)

    @classmethod
    def from_json(
        cls,
        payload: str,
    ) -> Any:
        document = json.loads(payload)

        if not isinstance(document, dict):
            raise TypeError(
                "JSON root must be an object"
            )

        return cls.from_dict(document)


# RAGStatus 区分成功、无证据、失败和取消。
class RAGStatus(str, Enum):
    SUCCEEDED = "succeeded"
    NO_EVIDENCE = "no_evidence"
    FAILED = "failed"
    CANCELLED = "cancelled"


# TraceStatus 记录开始、成功、失败、重试、fallback、超时、熔断和拒绝。
class TraceStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    FALLBACK_USED = "fallback_used"
    TIMED_OUT = "timed_out"
    CIRCUIT_OPEN = "circuit_open"
    REJECTED = "rejected"


# FailureCode 固定所有失败原因，避免后续到处传裸字符串
class FailureCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    NO_EVIDENCE = "no_evidence"
    RETRIEVAL_ERROR = "retrieval_error"
    NO_CANDIDATES = "no_candidates"
    CONTEXT_BUDGET_EXCEEDED = (
        "context_budget_exceeded"
    )
    MODEL_TIMEOUT = "model_timeout"
    MODEL_ERROR = "model_error"
    MODEL_FORMAT_ERROR = "model_format_error"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"
    PERMISSION_DENIED = "permission_denied"
    INJECTION_BLOCKED = "injection_blocked"
    INTERNAL_ERROR = "internal_error"

# RetrievalMode 固定 Vector、BM25、RRF、Rerank 和 fallback 模式。
class RetrievalMode(str, Enum):
    VECTOR = "vector"
    BM25 = "bm25"
    # 它表示 Vector 和 BM25 已经并行执行，但还没做 RRF。
    HYBRID_SOURCES = "hybrid_sources"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RERANK = "hybrid_rerank"
    HYBRID_FALLBACK = "hybrid_fallback"

# TrustLevel 和 ContentType 为后续 Injection 防护和 Citation 做准备。
class TrustLevel(str, Enum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    UNKNOWN = "unknown"


class ContentType(str, Enum):
    SYSTEM_INSTRUCTION = "system_instruction"
    USER_INPUT = "user_input"
    RETRIEVED_DOCUMENT = "retrieved_document"
    TOOL_RESULT = "tool_result"
    GENERATED_ANSWER = "generated_answer"

## 整体定位

# 这一组类是整个 RAG 主链路的**输入输出第一站**：

# - 上游：对接 FastAPI 的 `/ask` 接口，接收前端请求
# - 下游：传给检索模块执行，检索完成后返回标准结果给上下文组装模块
# - 所有类全部继承 `ContractModel`，天然拥有序列化 / 反序列化能力
# - 所有类都用 `__post_init__` + `_require` 做字段合法性校验，对象一创建就自动校验，把非法数据拦在契约层

# 1. `HistoryMessage` —— 单条对话历史消息
# **设计意图**：
# - 对齐大模型通用的消息格式，兼容普通对话和工具调用场景
# - `metadata` 做预留，后面可以加时间戳、token 数、来源等信息，不用改契约结构
# - 后面 B06 上下文组装时，会把历史消息按预算裁剪后拼进提示词
@dataclass
class HistoryMessage(ContractModel):
    role: str                # 角色：user/assistant/tool
    content: str             # 消息内容
    name: str = ""           # 工具调用时的名称，可选
    tool_call_id: str = ""   # 工具调用ID，可选
    metadata: dict[str, Any] = field(default_factory=dict) # 扩展元数据，预留字段

    def __post_init__(self) -> None:
        _require(
            bool(self.role.strip()),
            "role cannot be empty",
        )
        _require(
            isinstance(self.content, str),
            "content must be a string",
        )


# 2. `RetrievalFilters` —— 检索过滤条件
# **设计意图**：
# - 统一所有过滤维度，后面不管是向量检索还是 BM25，都按这个结构传过滤条件
# - 集合用 `tuple` 不用 `list`：tuple 不可变，契约对象创建后就不能中途修改，避免业务代码意外改值导致 bug
# - 对应 B02 任务里的「Metadata Filter」，过滤条件会通过这个契约传入检索模块
@dataclass
class RetrievalFilters(ContractModel):
    sources: tuple[str, ...] = ()       # 限定数据源
    document_ids: tuple[str, ...] = ()  # 限定文档ID
    pages: tuple[int, ...] = ()         # 限定页码
    metadata_equals: dict[str, Any] = field(default_factory=dict)     # 元数据精确匹配


    def __post_init__(self) -> None:
        _require(
            all(page >= 1 for page in self.pages),
            "page numbers must be >= 1",
        )


# 3. `TokenBudget` —— Token 预算控制
# **设计意图**：
# - 把上下文窗口量化成明确的配额，后面 B06 Context Packing 就按这个配额去裁剪内容
# - 避免之前 “随便拼 top-k，最后超窗口报错” 的问题
# - 可以根据不同模型、不同场景灵活调整分配比例
@dataclass
class TokenBudget(ContractModel):
    total_tokens: int = 6000       # 总预算
    retrieval_tokens: int = 3000   # 检索文档占用预算
    history_tokens: int = 1500     # 对话历史占用预算
    generation_tokens: int = 1500  # 模型生成预留预算

    def __post_init__(self) -> None:
        values = (
            self.total_tokens,
            self.retrieval_tokens,
            self.history_tokens,
            self.generation_tokens,
        )

        _require(
            all(value >= 0 for value in values),
            "token budgets cannot be negative",
        )
        _require(
            self.retrieval_tokens
            + self.history_tokens
            <= self.total_tokens,
            "retrieval and history budgets exceed total",
        )

# 4. `RAGRequest` —— RAG 请求根契约
# - **对应业务流程**：
#   1. FastAPI 接口接收 JSON，直接 `RAGRequest.from_json()` 转成对象
#   2. 传给 `RAGRuntime` 执行整个流程
#   3. 后续所有阶段（检索、重排、生成）都共享这个请求对象里的参数
# - **设计意图**：
# 所有输入信息收敛到一个对象里，不用在函数之间传十几个参数，接口统一、易扩展。
@dataclass
class RAGRequest(ContractModel):
    question: str                  # 用户问题
    thread_id: str                 # 会话ID，多轮对话用
    run_id: str | None = None      # 单次请求追踪ID
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)      # 检索过滤条件
    history: tuple[HistoryMessage, ...] = ()  # 对话历史
    budget: TokenBudget = field(default_factory=TokenBudget)            # Token预算
    allow_rerank: bool = False     # 是否允许重排
    metadata: dict[str, Any] = field(default_factory=dict)       # 扩展元数据


    def __post_init__(self) -> None:
        _require(
            bool(self.question.strip()),
            "question cannot be empty",
        )
        _require(
            bool(self.thread_id.strip()),
            "thread_id cannot be empty",
        )

# 5. `RetrievalCandidate` —— 单个检索候选块
# **核心设计亮点**：
# 一个对象承载**全链路所有阶段的排名和分数**，每经过一步处理（向量检索、BM25、RRF 融合、重排），就把对应阶段的排名和分数填进去，不覆盖之前的值。
# - 好处 1：后面做链路追踪时，可以看到每个块在每一步的排名变化，方便排查问题
# - 好处 2：做效果对比时，直接对比同一个块的向量分、RRF 分、重排分，非常清晰
# - 好处 3：不用每一步都换一种数据结构，全程复用这一个契约
@dataclass
class RetrievalCandidate(ContractModel):
    chunk_id: str       # 文本块唯一ID
    text: str           # 块内容
    source: str         # 来源文档
    page: int = 0       # 页码
    # 各路检索的排名与分数
    vector_rank: int | None = None
    vector_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    rrf_rank: int | None = None
    rrf_score: float | None = None
    rerank_rank: int | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(
            bool(self.chunk_id.strip()),
            "chunk_id cannot be empty",
        )
        _require(
            bool(self.text.strip()),
            "candidate text cannot be empty",
        )
        _require(
            bool(self.source.strip()),
            "candidate source cannot be empty",
        )
        _require(
            self.page >= 0,
            "candidate page cannot be negative",
        )


# 6. `RetrievalResult` —— 检索阶段输出结果
# - **对应业务流程（B03~B05）**：
#   1. B03 并行检索：把向量结果填进 `vector_candidates`，BM25 结果填进 `bm25_candidates`
#   2. B04 RRF 融合：融合后结果填进 `fused_candidates`
#   3. B05 重排：重排后结果填进 `reranked_candidates`
#   4. 最终筛选：选中送进上下文的填进 `selected_candidates`
# - **设计意图**：
# 每一步的结果都独立保留，不覆盖原始数据。调试的时候可以直接看每一步的输出差异，出问题快速定位是哪一步出了错；做评测的时候也可以直接对比不同阶段的结果质量。
@dataclass
class RetrievalResult(ContractModel):
    mode: RetrievalMode               # 本次使用的检索模式
    vector_candidates: tuple[RetrievalCandidate, ...] = ()  # 向量检索原始结果
    bm25_candidates: tuple[RetrievalCandidate, ...] = ()    # BM25原始结果
    fused_candidates: tuple[RetrievalCandidate, ...] = ()   # RRF融合后结果
    reranked_candidates: tuple[RetrievalCandidate, ...] = ()# 重排后结果
    selected_candidates: tuple[RetrievalCandidate, ...] = ()# 最终选中结果
    latency_ms: float = 0.0           # 检索总耗时
    fallback_used: str = ""           # 是否触发了降级
    metadata: dict[str, Any] = field(default_factory=dict)


# 1. `EvidenceItem` —— 进入上下文的证据项
# - **和 `RetrievalCandidate` 的区别**：
#   - `RetrievalCandidate` 是检索阶段的原始产物，带向量 / BM25/RRF/ 重排 全链路排名分数，用于过程对比
#   - `EvidenceItem` 是检索最终的交付产物，只保留最终得分，新增了安全评级、可疑标记，是给上下文组装模块用的
# - **对应业务**：B06 Context Packing 模块会把检索候选处理成证据项，再组装进上下文
@dataclass
class EvidenceItem(ContractModel):
    evidence_id: str          # 证据唯一ID
    chunk_id: str             # 对应原始检索块ID
    source: str               # 来源文档
    page: int                 # 页码
    text: str                 # 证据文本
    score: float = 0.0        # 最终相关性得分
    trust_level: TrustLevel = TrustLevel.UNTRUSTED   # 可信等级（可信/不可信/未知）
    suspicious_instruction: bool = False  # 是否包含可疑指令（注入检测标记）
    content_type: ContentType = ContentType.RETRIEVED_DOCUMENT # 内容类型
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(
            bool(self.evidence_id.strip()),
            "evidence_id cannot be empty",
        )
        _require(
            bool(self.chunk_id.strip()),
            "evidence chunk_id cannot be empty",
        )
        _require(
            bool(self.source.strip()),
            "evidence source cannot be empty",
        )
        _require(
            bool(self.text.strip()),
            "evidence text cannot be empty",
        )
        _require(
            self.page >= 0,
            "evidence page cannot be negative",
        )

# 2. `CitationContract` —— 回答中的引用标记
# - **设计意图**：引用和证据分离，回答里只存引用索引，不重复存证据全文，结构轻量。前端点击引用标号时，通过 `evidence_id` 就能定位到完整证据内容。
# - **对应业务**：B07 模型生成回答后，会解析回答里的引用标记，生成对应的 `CitationContract` 列表
@dataclass
class CitationContract(ContractModel):
    citation_id: str   # 引用编号ID（比如 "c1"）
    evidence_id: str   # 关联的证据ID
    source: str        # 来源文档
    page: int          # 页码

    def __post_init__(self) -> None:
        _require(
            bool(self.citation_id.strip()),
            "citation_id cannot be empty",
        )
        _require(
            bool(self.evidence_id.strip()),
            "citation evidence_id cannot be empty",
        )
        _require(
            bool(self.source.strip()),
            "citation source cannot be empty",
        )
        _require(
            self.page >= 0,
            "citation page cannot be negative",
        )

# 3. `ConflictInfo` —— 证据冲突信息
# **对应业务**：B06 Context Packing 里的冲突检测模块产出，用于在回答里做冲突提示，避免误导用户
@dataclass
class ConflictInfo(ContractModel):
    topic: str                  # 冲突主题
    source_a: str
    source_b: str                # 冲突双方来源
    differences: tuple[str, ...] = ()  # 具体差异点
    requires_disclosure: bool = True   # 是否需要向用户披露


    def __post_init__(self) -> None:
        _require(
            bool(self.topic.strip()),
            "conflict topic cannot be empty",
        )
        _require(
            bool(self.source_a.strip()),
            "conflict source_a cannot be empty",
        )
        _require(
            bool(self.source_b.strip()),
            "conflict source_b cannot be empty",
        )


# 4. `InjectionFinding` —— 注入检测发现
# **对应业务**：注入防护模块扫描每个证据块后产出，高危内容会被拦截，中低危会标记并记录
@dataclass
class InjectionFinding(ContractModel):
    finding_id: str
    chunk_id: str
    severity: str       # 严重等级：low/medium/high/critical
    matched_pattern: str # 匹配到的风险模式
    action: str         # 采取的动作：标记/移除/拦截
    excerpt: str = ""        # 可疑片段


    def __post_init__(self) -> None:
        _require(
            bool(self.finding_id.strip()),
            "finding_id cannot be empty",
        )
        _require(
            bool(self.chunk_id.strip()),
            "injection chunk_id cannot be empty",
        )
        _require(
            self.severity
            in {
                "low",
                "medium",
                "high",
                "critical",
            },
            "invalid injection severity",
        )
        _require(
            bool(self.action.strip()),
            "injection action cannot be empty",
        )

# 5. `ModelUsage` —— 模型用量统计
# **对应业务**：B07 模型调用完成后填充，最终随回答一起返回，也用于后续的成本统计
@dataclass
class ModelUsage(ContractModel):
    input_tokens: int = 0      # 输入Token数    
    output_tokens: int = 0     # 输出Token数
    total_tokens: int = 0      # 总计
    cache_read_tokens: int = 0 # 缓存命中的Token数


    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cache_read_tokens,
        )

        _require(
            all(value >= 0 for value in values),
            "token usage cannot be negative",
        )

# **B02 阶段 Query Rewrite（查询重写）模块的输出契约**
@dataclass
class QueryRewriteResult(ContractModel):
    original_query: str
    normalized_query: str
    semantic_query: str
    keyword_query: str
    inferred_filters: RetrievalFilters = field(
        default_factory=RetrievalFilters
    )
    version_policy: str = "latest"
    must_disclose_conflicts: bool = True
    reason: str = ""
    raw_model_output: str = ""
    model_name: str = ""
    usage: ModelUsage = field(
        default_factory=ModelUsage
    )
    fallback_used: bool = False
    fallback_reason: str = ""
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        _require(
            bool(self.original_query.strip()),
            "original_query cannot be empty",
        )
        _require(
            bool(self.normalized_query.strip()),
            "normalized_query cannot be empty",
        )
        _require(
            bool(self.semantic_query.strip()),
            "semantic_query cannot be empty",
        )
        _require(
            bool(self.keyword_query.strip()),
            "keyword_query cannot be empty",
        )
        _require(
            self.version_policy
            in {
                "latest",
                "all",
                "explicit",
            },
            "invalid version_policy",
        )
        _require(
            self.latency_ms >= 0,
            "rewrite latency cannot be negative",
        )



# 6. `ContextPack` —— 组装完成的上下文包
# **B06 Context Packing 模块的核心输出**，是送给大模型的最终上下文成品。
# - **关键校验**：所有引用的 `evidence_id` 必须在证据列表中真实存在，杜绝 “悬空引用”
# - **设计定位**：它是检索模块和生成模块之间的**标准接口**。检索侧只负责产出 ContextPack，生成侧只负责接收 ContextPack，两边完全解耦。替换检索算法或者替换模型，都不会影响对方
@dataclass
class ContextPack(ContractModel):
    context_text: str = ""           # 拼接好的完整上下文文本
    evidence: tuple[EvidenceItem, ...] = ()  # 所有用到的证据列表
    citations: tuple[CitationContract, ...] = () # 对应的引用列表
    conflicts: tuple[ConflictInfo, ...] = ()   # 检测到的冲突
    injections: tuple[InjectionFinding, ...] = () # 检测到的注入
    context_tokens: int = 0         # 上下文总Token数
    budget_used: int = 0            # 实际使用的预算
    duplicate_text_count: int = 0   # 去重统计
    source_diversity: float = 0.0     # 来源多样性得分
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(
            self.context_tokens >= 0,
            "context tokens cannot be negative",
        )
        _require(
            self.budget_used >= 0,
            "budget_used cannot be negative",
        )
        _require(
            self.duplicate_text_count >= 0,
            "duplicate_text_count cannot be negative",
        )

        evidence_ids = {
            item.evidence_id
            for item in self.evidence
        }

        for citation in self.citations:
            _require(
                citation.evidence_id
                in evidence_ids,
                (
                    "citation references missing evidence: "
                    f"{citation.evidence_id}"
                ),
            )

# 7. `RAGFailure` —— 统一失败信息
# 全系统标准化的错误结构，替代零散的异常抛出。
# - **对应业务**：B08 超时、重试、降级逻辑的核心依据。遇到错误时，根据 `retryable` 决定是否重试，根据 `terminal` 决定是否走 fallback 链路
# - **设计价值**：错误码标准化，前端、日志、监控都可以根据 `code` 做统一处理，不用解析错误文本
@dataclass
class RAGFailure(ContractModel):
    code: FailureCode    # 标准错误码（枚举）
    message: str         # 错误描述
    stage: str = ""           # 发生在哪个阶段
    retryable: bool = False      # 是否可重试
    terminal: bool = True       # 是否是终态失败
    details: dict[str, Any] = field(default_factory=dict)


    def __post_init__(self) -> None:
        _require(
            bool(self.message.strip()),
            "failure message cannot be empty",
        )

# 8. `TraceEvent` —— 链路追踪事件
# 全链路追踪的最小单元，**C 阶段可观测能力的基础**。
# - **对应业务**：RAG 流程的每一步（检索、融合、重排、生成、容错）都会产生一个 TraceEvent，最终按时间顺序拼成完整的执行链路
# - **设计价值**：有了它，才能做到 “每一步耗时多少、成功还是失败、重试了几次” 都可查可追溯，是后面做调试、监控、性能优化的基础
@dataclass
class TraceEvent(ContractModel):
    event_id: str
    run_id: str          # 单次请求ID
    stage: str           # 所属阶段（retrieval/rerank/generation...）
    operation: str       # 具体操作（vector_search/rrf_fuse...）
    status: TraceStatus  # 状态（枚举）
    attempt: int = 1     # 第几次尝试（重试计数）
    action: str = ""          # 执行的动作
    started_at: str = field(default_factory=utc_now)      # 开始时间
    finished_at: str = ""     # 结束时间
    duration_ms: float = 0.0   # 耗时
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(
            bool(self.event_id.strip()),
            "event_id cannot be empty",
        )
        _require(
            bool(self.run_id.strip()),
            "trace run_id cannot be empty",
        )
        _require(
            bool(self.stage.strip()),
            "trace stage cannot be empty",
        )
        _require(
            bool(self.operation.strip()),
            "trace operation cannot be empty",
        )
        _require(
            self.attempt >= 1,
            "trace attempt must be >= 1",
        )
        _require(
            self.duration_ms >= 0,
            "trace duration cannot be negative",
        )

# 9. `RAGAnswer` —— 生成模块的最终回答
# 模型生成侧的输出契约，也是前端最关心的核心结果。**关键联动校验**：
# - 状态为 `SUCCEEDED` 时，回答文本不能为空
# - 状态为 `FAILED` 时，必须携带失败详情
# 从契约层面保证 “状态和内容一致”，避免出现 “状态成功但回答为空” 的异常数据
@dataclass
class RAGAnswer(ContractModel):
    status: RAGStatus          # 最终状态（成功/无证据/失败/取消）
    answer: str = ""           # 回答文本
    citations: tuple[CitationContract, ...] = () # 引用列表
    usage: ModelUsage = field(default_factory=ModelUsage)          # Token用量
    latency_ms: float = 0.0    # 生成耗时
    failure: RAGFailure | None = None # 失败详情
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(
            self.latency_ms >= 0,
            "answer latency cannot be negative",
        )

        if self.status is RAGStatus.SUCCEEDED:
            _require(
                bool(self.answer.strip()),
                "successful answer cannot be empty",
            )

        if self.status is RAGStatus.FAILED:
            _require(
                self.failure is not None,
                "failed answer requires failure details",
            )


# 10. `RAGResult` —— 全链路完整结果
# **整个 RAG Runtime 的最终返回值**，包含一次请求从入站到出站的全部信息。
# - **设计定位**：这是一份完整的「请求执行档案」。不仅包含给用户的回答，还包含了检索过程、上下文内容、每一步的追踪事件。
# - **用途**：
#   - 接口返回给前端：可以裁剪后只返回 answer 部分
#   - 存日志 / 数据库：完整存储，方便后续排查问题、做效果分析
#   - 调试排查：出问题时直接看完整 Result，就能定位是哪个环节出了错
@dataclass
class RAGResult(ContractModel):
    request: RAGRequest                # 原始请求
    answer: RAGAnswer                  # 最终回答
    retrieval: RetrievalResult | None = None  # 检索全过程详情
    context: ContextPack | None = None        # 上下文组装详情
    trace: tuple[TraceEvent, ...] = ()      # 全链路事件追踪
    rewrite: QueryRewriteResult | None = None   
    metadata: dict[str, Any] = field(default_factory=dict)

## 整体设计特点总结

# 1. **全链路闭环**：从 `RAGRequest` 进，到 `RAGResult` 出，覆盖请求、检索、上下文、生成、回答、追踪全流程，数据结构完全标准化
# 2. **分层解耦**：每个阶段都有明确的输入输出契约，模块之间只对接契约，不依赖内部实现。换检索算法、换模型、加安全策略，都不会影响其他模块
# 3. **创建即合法**：所有契约都带字段校验，只要对象能创建出来，就一定符合规范，业务代码不用重复做校验
# 4. **可观测性内置**：TraceEvent 贯穿全程，每个阶段的状态、耗时、重试都可追溯，为后续 C 阶段的监控能力打好了地基
# 5. **安全能力原生**：注入检测、冲突检测都有对应的契约结构，安全不是外挂功能，而是上下文的原生属性