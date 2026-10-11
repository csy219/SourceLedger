import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from runtime.api.S19_2_app import (
    create_app,
)


def fake_ask(
    question: str,
    thread_id: str,
) -> dict:
    return {
        "answer": (
            "文档加载、文本分块、向量化、"
            "入库、检索和生成回答。"
        ),
        "citations": [
            {
                "source": "AI应用开发知识手册.pdf",
                "page": 2,
            }
        ],
    }


def main() -> int:
    app = create_app()

    with TestClient(app) as client:
        app.state.ask_function = fake_ask

        session_response = client.post(
            "/sessions",
            json={
                "user_id": "user-smoke",
                "title": "S19-4 smoke",
            },
        )
        session = session_response.json()

        request_id = uuid.uuid4().hex

        ask_payload = {
            "question": (
                "RAG 的完整流程有哪几步？"
            ),
            "thread_id": session["thread_id"],
            "request_id": request_id,
            "stream": False,
        }

        first_response = client.post(
            "/ask",
            json=ask_payload,
        )
        second_response = client.post(
            "/ask",
            json=ask_payload,
        )

        first = first_response.json()
        second = second_response.json()

        task_response = client.get(
            f"/tasks/{first['run_id']}"
        )
        task = task_response.json()

    passed = (
        session_response.status_code == 200
        and first_response.status_code == 200
        and second_response.status_code == 200
        and task_response.status_code == 200
        and first["replayed"] is False
        and second["replayed"] is True
        and first["run_id"] == second["run_id"]
        and task["status"] == "completed"
        and task["current_node"] == "finish"
    )

    output = {
        "session": session,
        "first_ask": first,
        "second_ask": second,
        "task": task,
        "passed": passed,
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    if not passed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())