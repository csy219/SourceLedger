import os
import time
from typing import Annotated, TypedDict

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from pdf_rag import search_knowledge as rag_search

SYSTEM_PROMPT = (
    "你是文档问答助手。回答必须基于 search_knowledge 工具检索到的资料；"
    "资料不足时明确说不知道，不要编造。"
    "回答末尾列出引用，格式：[文件名 第X页]。"
)


@tool
def search_knowledge(query: str) -> str:
    """根据问题检索已上传的文档，返回相关原文片段和来源"""
    hits = rag_search(query, top_k=4, threshold=0.5)
    if not hits:
        return "没有检索到相关资料。"
    return "\n\n".join(
        f"[{h['source']} 第{h['page']}页] {h['text']}" for h in hits
    )


llm = ChatOpenAI(
    model="deepseek-v4-flash",
    base_url="https://api.deepseek.com",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0,
    max_tokens=2000,
).bind_tools([search_knowledge])


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def agent_node(state: State) -> dict:
    messages = state["messages"]
    response = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), *messages])
    return {"messages": [response]}


builder = StateGraph(State)

builder.add_node("agent", agent_node)
builder.add_node("tools", ToolNode([search_knowledge]))

builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)


def ask(question: str, thread_id: str = "default") -> dict:
    started = time.perf_counter()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {"messages": [HumanMessage(content=question)]},
        config,
    )
    answer = result["messages"][-1].content or ""

    hits = rag_search(question, top_k=4, threshold=0.5)
    citations = [
        {"source": h["source"], "page": h["page"], "distance": h["distance"]}
        for h in hits
    ]

    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cache_read_tokens = 0

    for message in result["messages"]:
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            continue

        input_tokens += int(usage.get("input_tokens", 0) or 0)
        output_tokens += int(usage.get("output_tokens", 0) or 0)
        total_tokens += int(usage.get("total_tokens", 0) or 0)
        input_details = usage.get("input_token_details") or {}
        cache_read_tokens += int(
            input_details.get("cache_read", 0) or 0
        )

    fallback_context_tokens = sum(
        max(1, len(str(hit["text"])) // 2)
        for hit in hits
    )
    latency_ms = (time.perf_counter() - started) * 1000

    return {
        "answer": answer,
        "citations": citations,
        "context_tokens_est": (
            input_tokens
            if input_tokens > 0
            else fallback_context_tokens
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read_tokens,
        "latency_ms": round(latency_ms, 2),
    }
