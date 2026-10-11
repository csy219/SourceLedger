"""FastAPI-compatible adapter for the advanced RAG runtime."""

from __future__ import annotations

import time
from typing import Any

from dotenv import load_dotenv

from runtime.rag_contracts import RAGRequest
from runtime.rag_runtime import (
    RAGRuntime,
)


load_dotenv()


class AskService:
    def __init__(
        self,
        runtime: RAGRuntime | None = None,
    ) -> None:
        self.runtime = (
            runtime
            if runtime is not None
            else RAGRuntime()
        )

    @staticmethod
    def _citations_to_dicts(
        citations: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        return [
            {
                "citation_id": (
                    item.citation_id
                ),
                "evidence_id": (
                    item.evidence_id
                ),
                "source": item.source,
                "page": item.page,
            }
            for item in citations
        ]

    def ask(
        self,
        question: str,
        thread_id: str = "default",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()

        request = RAGRequest(
            question=question,
            thread_id=thread_id,
            run_id=run_id
        )

        prepared = self.runtime.prepare(
            request
        )
        retrieved = self.runtime.retrieve(
            prepared,
            candidate_k=20,
        )
        packaged = self.runtime.pack_context(
            retrieved,
            retrieval_budget=1800,
        )
        generated = self.runtime.generate(
            packaged
        )

        answer = generated.answer
        context = generated.context
        retrieval = generated.retrieval

        total_latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )

        answer_text = answer.answer

        if (
            not answer_text
            and answer.failure is not None
        ):
            answer_text = (
                answer.failure.message
            )

        return {
            "answer": answer_text,
            "citations": (
                self._citations_to_dicts(
                    answer.citations
                )
            ),
            "context_tokens_est": (
                context.context_tokens
            ),
            "input_tokens": (
                answer.usage.input_tokens
            ),
            "output_tokens": (
                answer.usage.output_tokens
            ),
            "total_tokens": (
                answer.usage.total_tokens
            ),
            "cache_read_tokens": (
                answer.usage.cache_read_tokens
            ),
            "latency_ms": total_latency_ms,
            "generation_latency_ms": (
                answer.latency_ms
            ),
            "retrieval_latency_ms": (
                retrieval.latency_ms
            ),
            "run_id": generated.request.run_id,
            "thread_id": (
                generated.request.thread_id
            ),
            "status": answer.status.value,
            "failure_code": (
                answer.failure.code.value
                if answer.failure
                else ""
            ),
            "failure_message": (
                answer.failure.message
                if answer.failure
                else ""
            ),
            "retrieval_mode": (
                retrieval.mode.value
            ),
            "vector_count": len(
                retrieval.vector_candidates
            ),
            "bm25_count": len(
                retrieval.bm25_candidates
            ),
            "rrf_count": len(
                retrieval.fused_candidates
            ),
            "rerank_count": len(
                retrieval.reranked_candidates
            ),
            "context_stats": (
                context.metadata.get(
                    "context_stats",
                    {},
                )
            ),
            "conflict_count": len(
                context.conflicts
            ),
            "injection_count": len(
                context.injections
            ),
            "trace": [
                event.to_dict()
                for event in generated.trace
            ],
        }


_ask_service: AskService | None = None


def get_ask_service() -> AskService:
    global _ask_service

    if _ask_service is None:
        _ask_service = AskService()

    return _ask_service


def ask(
    question: str,
    thread_id: str = "default",
    run_id: str | None = None,
) -> dict[str, Any]:
    return get_ask_service().ask(
        question=question,
        thread_id=thread_id,
        run_id=run_id,
    )

# 为什么这样设计：
# - 对外函数签名仍是：
# ask(question, thread_id) -> dict
# - 内部实际执行完整高级 RAG：
# prepare
# -> retrieve
# -> pack_context
# -> generate
# - 返回结构与旧 /ask 兼容。
# - 额外返回 Trace、检索数量、Context 统计和失败信息。
# - 不会再调用旧 agent.ask 或 pdf_rag.search_knowledge。
# - run_id 贯穿 Query Rewrite、检索、Context 和 Generation。