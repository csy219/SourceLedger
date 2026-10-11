# 这是 **流式问答接口 `/ask/stream` 的冒烟测试脚本**，基于 FastAPI `TestClient` 实现进程内接口测试，
# 通过 Mock 替换 Agent 问答函数隔离外部依赖，完整验证 SSE 流式输出的格式合规性、事件完整性、文本正确性。核心验证目标：
# 1. 接口返回 200 状态码，内容类型为 SSE 格式
# 2. 完整输出 `start`、`token`、`citation`、`done` 四类标准事件
# 3. 所有 `token` 事件的增量文本拼接后，与完整回答完全一致
# 4. 输出中无 `error` 错误事件
# 最终输出结构化测试报告，通过程序退出码标识测试结果，可集成到 CI 流水线
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

        response = client.post(
            "/ask/stream",
            json={
                "question": (
                    "RAG 的完整流程有哪几步？"
                ),
                "thread_id": (
                    "thread-stream-smoke"
                ),
                "request_id": uuid.uuid4().hex,
                "stream": True,
            },
        )

    text = response.text

    token_chunks = []

    for block in text.split("\n\n"):
        if not block.startswith("event: token"):
            continue

        data_line = next(
            (
                line
                for line in block.splitlines()
                if line.startswith("data: ")
            ),
            "",
        )
        if not data_line:
            continue

        payload = json.loads(
            data_line.removeprefix("data: ")
        )
        token_chunks.append(
            payload["delta"]
        )

    reconstructed = "".join(token_chunks)

    passed = (
        response.status_code == 200
        and "event: start" in text
        and "event: token" in text
        and "event: citation" in text
        and "event: done" in text
        and "event: error" not in text
        and reconstructed
        == (
            "文档加载、文本分块、向量化、"
            "入库、检索和生成回答。"
        )
    )

    output = {
        "status_code": response.status_code,
        "content_type": response.headers.get(
            "content-type"
        ),
        "reconstructed_answer": reconstructed,
        "events": {
            "start": (
                "event: start" in text
            ),
            "token": (
                "event: token" in text
            ),
            "citation": (
                "event: citation" in text
            ),
            "done": (
                "event: done" in text
            ),
            "error": (
                "event: error" in text
            ),
        },
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