import json
import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.api.S19_1_schemas import (
    AskRequest,
    AskResponse,
    CitationItem,
    HealthResponse,
    ReadinessResponse,
    TaskStatus,
    TaskStatusResponse,
)


def main() -> int:
    ask_request = AskRequest(
        question="RAG 的完整流程有哪几步？",
        thread_id="thread-contract-smoke",
        request_id="request-contract-1",
        stream=False,
    )

    ask_response = AskResponse(
        run_id="run-contract-1",
        thread_id="thread-contract-smoke",
        status=TaskStatus.COMPLETED,
        answer=(
            "文档加载、文本分块、向量化、入库、"
            "检索和生成回答。"
        ),
        citations=[
            CitationItem(
                citation_id="C1",
                source="AI应用开发知识手册.pdf",
                page=2,
            )
        ],
        context_tokens_est=120,
        latency_ms=35.2,
        replayed=False,
    )

    task_status = TaskStatusResponse(
        run_id="run-contract-1",
        thread_id="thread-contract-smoke",
        status=TaskStatus.COMPLETED,
        current_node="finish",
        step_count=1,
        max_steps=20,
    )

    health = HealthResponse(
        status="ok",
        service="source-ledger",
        version="0.1.0",
    )

    readiness = ReadinessResponse(
        ready=True,
        database=True,
        redis=True,
        details={
            "database": "ok",
            "redis": "ok",
        },
    )

    output = {
        "ask_request": (
            ask_request.model_dump()
        ),
        "ask_response": (
            ask_response.model_dump()
        ),
        "task_status": (
            task_status.model_dump()
        ),
        "health": health.model_dump(),
        "readiness": readiness.model_dump(),
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
