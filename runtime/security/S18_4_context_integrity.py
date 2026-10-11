# 这是**RAG 系统的上下文完整性防护模块**，核心作用是保障检索上下文的可靠性与生成回答的引用合规性，覆盖三大核心能力：

# 1. 内容污染检测：校验可疑 / 不可信内容是否被正确插入警告标识
# 2. 多来源冲突检测：校验不同来源的内容冲突是否被准确识别
# 3. 引用合法性校验：校验模型回答中的引用标记是否对应真实存在的检索文档
# 同时封装了上下文打包工具，所有评估结果均以标准化只读结构输出。
import re
from dataclasses import dataclass
from typing import Any

from evaluation.S13_3_context_trimmer import (
    build_retrieval_block,
)
from evaluation.S13_2_context_packer import (
    pack_context,
)


# **变量`CITATION_PATTERN`**：预编译的引用格式正则表达式，用于从模型回答中提取引用标记。
# - 正则拆解：`\[`匹配字面左方括号，`(C\d+)`是捕获组，匹配大写字母 C 后接数字（如`C1`、`C12`），`\]`匹配字面右方括号；
# - 匹配目标：`[C1]`、`[C5]`这类标准引用标记；
# - 预编译可提升多次匹配的性能，是引用校验的核心匹配规则。
CITATION_PATTERN = re.compile(
    r"\[(C\d+)\]"
)


# 3. 评估结果数据类（全部为冻结只读类）

# PollutionAssessment 污染评估结果
# - `suspicious_count: int`：上下文中被识别为可疑 / 不可信的内容片段数量。
# - `context_contains_warning: bool`：打包后的上下文文本中是否插入了「不可信内容警告」警示标识。
# - `passed: bool`：污染检测是否通过，即可疑内容是否被正确标记警告。
@dataclass(frozen=True)
class PollutionAssessment:
    suspicious_count: int
    context_contains_warning: bool
    passed: bool


# ConflictAssessment 冲突评估结果
# - `has_conflict: bool`：是否检测到不同来源之间存在内容冲突。
# - `sources: tuple[str, ...]`：产生冲突的所有来源名称，元组形式保证不可变。
# - `both_sources_present: bool`：预期的冲突来源是否全部出现在上下文的引用列表中。
# - `passed: bool`：冲突检测是否通过，即冲突是否被正确识别且来源完整。
@dataclass(frozen=True)
class ConflictAssessment:
    has_conflict: bool
    sources: tuple[str, ...]
    both_sources_present: bool
    passed: bool


# CitationAssessment 引用评估结果
# - `cited_ids: tuple[str, ...]`：模型回答中实际出现的所有引用 ID，去重并保留出现顺序。
# - `valid_ids: tuple[str, ...]`：所有合法的引用 ID，对应检索文档的真实引用编号。
# - `invalid_ids: tuple[str, ...]`：回答中出现的非法引用 ID，即不存在对应检索文档的编造引用。
# - `passed: bool`：引用校验是否通过，无非法引用即为通过。
@dataclass(frozen=True)
class CitationAssessment:
    cited_ids: tuple[str, ...]
    valid_ids: tuple[str, ...]
    invalid_ids: tuple[str, ...]
    passed: bool


# ContextIntegrityGuard 上下文完整性防护主类
class ContextIntegrityGuard:

    # - 作用：封装底层`pack_context`工具，配置固定的打包参数，将原始检索候选处理为标准化上下文结构。
    # - 参数`candidates`：原始检索候选文档列表，每个元素是包含文本、来源、页码等字段的字典。
    # - 打包参数说明：
    # - `retrieval_budget=1800`：上下文总字符数预算，控制上下文长度上限；
    # - `max_chunk_per_page=2`：单页文档最多选取 2 个文本块；
    # - `max_chunk_per_parent=2`：单个父文档最多选取 2 个文本块；
    # - 返回值：打包后的上下文字典，包含`context_text`（上下文正文）、`stats`（统计信息）、`citations`（引用列表）、`conflict`（冲突检测结果）等字段。
    def pack(
    self,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
        return pack_context(
            candidates=candidates,
            retrieval_budget=1800,
            max_chunk_per_page=2,
            max_chunk_per_parent=2,
        )


    # assess_pollution 内容污染评估方法
    def assess_pollution(
        self,
        packed:dict[str,Any]
    )->PollutionAssessment:
        # **变量`suspicious_count`**：从打包结果的统计字段中取出可疑内容的数量并转为整数，代表上下文中被识别为不可信的内容片段总数。
        suspicious_count=int(packed["stats"]["suspicious_count"])
        # **变量`context_contains_warning`**：布尔值，判断打包后的上下文正文中是否包含「不可信内容警告」提示语，用于验证打包器是否对可疑内容插入了警示标识。
        rendered = build_retrieval_block(
                packed["retrieval_context"],
                packed["conflict"],
            )

        context_contains_warning = (
                "不可信内容警告" in rendered
            )
        return PollutionAssessment(
            suspicious_count=suspicious_count,
            context_contains_warning=context_contains_warning,
            # - 返回污染评估结果对象；
            # - `passed`判定逻辑：**存在可疑内容 且 上下文插入了对应警告**，才判定为通过。
            # - 核心逻辑：只要检测到可疑内容，就必须配套警告标识，才算防护机制生效。
            passed=(
                suspicious_count>0 
                and context_contains_warning
            ),
        )

    # assess_conflict 内容冲突评估方法
    def assess_conflict(
        self,
        packed:dict[str,Any],
        expected_sources:tuple[str,...],
    )->ConflictAssessment:
        # **变量`conflict`**：从打包结果中取出冲突检测结果字典，包含是否有冲突、冲突来源等信息
        conflict=packed["conflict"]

        # **变量`conflict_sources`**：冲突涉及的来源名称元组。
        # - `conflict.get("sources", [])`：安全获取冲突来源列表，不存在则返回空列表，避免键不存在报错；
        # - 全部转为字符串后转元组，保证结果不可变。
        conflict_sources = tuple(
            str(item)
            for item in conflict.get(
                "sources",
                [],
            )
        )
        # **变量`cited_sources`**：上下文中所有引用涉及的来源集合。
        # - 遍历打包结果的引用列表，提取每个引用的来源字段，通过集合去重；
        # - 用于校验冲突来源是否都真实存在于上下文引用中。
        cited_sources = {
            str(item["source"])
            for item in packed["citations"]
        }


        # **变量`both_sources_present`**：布尔值，判断所有预期的冲突来源是否都出现在引用来源集合中。
        # - `all()`遍历每个预期来源，全部存在才返回 True；
        # - 用于验证冲突检测的来源完整性，避免漏检冲突来源。
        both_sources_present=all(
            source in cited_sources
            for source in expected_sources
        )


        # - 返回冲突评估结果对象；
        # - `passed`判定逻辑：**检测到冲突存在 且 所有预期来源都在引用中**，才判定为通过。
        # - 核心逻辑：既要正确识别冲突，也要保证冲突涉及的来源都完整出现在上下文引用里，才算检测有效。
        return ConflictAssessment(
            has_conflict=bool(conflict.get("has_conflict")),
            sources=conflict_sources,
            both_sources_present=both_sources_present,
            passed=(bool(conflict.get("has_conflict"))
                    and both_sources_present)
        )

    # validate_answer_citations 引用合法性校验方法
    def validate_answer_citations(
        self,
        answer:str,
        citations:list[dict[str,Any]],
    )->CitationAssessment:
        # **变量`cited_ids`**：回答中实际出现的所有引用 ID，去重并保留首次出现顺序。
        # - `CITATION_PATTERN.findall(answer)`：用正则提取回答中所有`[Cx]`里的 ID 部分；
        # - `dict.fromkeys()`：利用字典键的唯一性去重，同时保留元素的出现顺序；
        # - 最终转为元组保证不可变。
        cited_ids=tuple(
            dict.fromkeys(
                CITATION_PATTERN.findall(answer)
            )
        )
        # **变量`valid_ids`**：所有合法引用 ID 的集合。
        # - 遍历引用列表，提取每个引用的`citation_id`（如`C1`、`C2`），通过集合去重；
        # - 作为校验引用合法性的基准。
        valid_ids = {
            str(item["citation_id"])
            for item in citations
        }
        # **变量`invalid_ids`**：回答中出现的非法引用 ID 元组。
        # - 遍历所有实际引用的 ID，筛选出不在合法 ID 集合中的 ID；
        # - 也就是模型编造的、不存在对应文档的引用。
        invalid_ids = tuple(
            citation_id
            for citation_id in cited_ids
            if citation_id not in valid_ids
        )

        return CitationAssessment(
            cited_ids=cited_ids,
            valid_ids=tuple(
                sorted(valid_ids)
            ),
            invalid_ids=invalid_ids,
            passed=not invalid_ids,
        )

