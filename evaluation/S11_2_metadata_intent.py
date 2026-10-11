import re
from typing import Any

MANUAL_SOURCE = "AI应用开发知识手册.pdf"
AGENT_SOURCE = "Agent平台需求说明.pdf"
TRAVEL_V1_SOURCE = "差旅报销制度_v1.pdf"
TRAVEL_V2_SOURCE = "差旅报销制度_v2.pdf"

SOURCE_KEYWORDS = {
    MANUAL_SOURCE: [
        "知识手册",
        "rag 手册",
        "rag",
        "langgraph",
        "mcp",
    ],
    AGENT_SOURCE: [
        "agent 平台",
        "agent平台",
        "repopilot",
        "平台需求",
    ],
}

TRAVEL_KEYWORDS = [
    "差旅",
    "住宿报销",
    "报销制度",
]

COMPARISON_KEYWORDS = [
    "两版",
    "两个版本",
    "有什么区别",
    "差异",
    "变化",
    "是否一致",
]

V1_PATTERNS = [
    re.compile(r"\bv\s*1\b", re.IGNORECASE),
    re.compile(r"版本\s*1"),
    re.compile(r"第一版"),
]

V2_PATTERNS = [
    re.compile(r"\bv\s*2\b", re.IGNORECASE),
    re.compile(r"版本\s*2"),
    re.compile(r"第二版"),
]

# 匹配关键词
def find_matches(
        lower:str,
        keywords:list[str],
)->list[str]:
    return [
        keyword
        for keyword in keywords
        if keyword.lower() in lower
    ]

# 元数据过滤 
def parse_metadata_intent(question:str)->dict[str,Any]:
    lowered=question.lower()
    matched_terms:list[str]=[]
    detected_sources:list[str]=[]
    # 通用文档
    for source,keywords in SOURCE_KEYWORDS.items():
        matches=find_matches(lowered,keywords)
        if matches:
            matched_terms.extend(matches)
            detected_sources.append(source)

    # 旅行（特例）
    travel_matches=find_matches(lowered,TRAVEL_KEYWORDS)
    if travel_matches:
        matched_terms.extend(travel_matches)

    comparison_matches=find_matches(
        lowered,
        COMPARISON_KEYWORDS,
    )
    is_comparison=bool(comparison_matches)
    matched_terms.extend(comparison_matches)

    if travel_matches:
        has_v1=any(
            pattern.search(question)
            for pattern in V1_PATTERNS
        )
        has_v2=any(
            pattern.search(question)
            for pattern in V2_PATTERNS
        )

        if is_comparison or not(has_v1 or has_v2):
            sources=[TRAVEL_V1_SOURCE,TRAVEL_V2_SOURCE]
            reason=(
                "comparison"
                if is_comparison
                else "travel_without_version"
            )

        elif has_v1 and has_v2:
            sources=[TRAVEL_V1_SOURCE,TRAVEL_V2_SOURCE]
            reason="both_versions"

        elif has_v1:
            sources=[TRAVEL_V1_SOURCE]
            reason="version"
        elif has_v2:
            sources=[TRAVEL_V2_SOURCE]
            reason="version"


        return {
            "sources":sources,
            "reason":reason,
            "is_comparison":is_comparison,
            "matched_terms":sorted(set(matched_terms))
        }

    unique_sources=sorted(set(detected_sources))

    if len(unique_sources)==1:
        return {
            "sources":unique_sources,
            "reason":"explicit_source",
            "is_comparison":False,
            "matched_terms":sorted(set(matched_terms))
        }

    reason=(
        "multi_source"
        if len(unique_sources)>1
        else "none"
    )
    return {
        "sources":[],
        "reason":reason,
        "is_comparison":False,
        "matched_terms":sorted(set(matched_terms))
    }

def build_chroma_where(
        sources:list[str],
)->dict[str,Any] | None:
    if not sources:
        return None

    if len(sources)==1:
        return {"source":{"$eq":sources[0]}}

    return {
        "$or":[
            {"source":{"$eq":source}}
            for source in sources
        ]
    }


def main() -> int:
    questions = [
        "知识手册里的 Checkpointer 有什么作用？",
        "RepoPilot 支持哪些用户角色？",
        "v2 的差旅住宿上限是多少？",
        "2026 年 11 月应该适用哪一版差旅制度？",
        "两版差旅制度是否都要求发票和审批记录？",
        "Agent 平台的安全原则和知识手册有什么共同点？",
        "RAG 的完整流程是什么？",
    ]

    for question in questions:
        intent=parse_metadata_intent(question)
        where=build_chroma_where(intent["sources"])
        print(f"\nquestion:{question}")
        print(intent)
        print("where",where)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())



