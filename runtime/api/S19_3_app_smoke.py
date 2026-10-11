import json
import sys
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


def main() -> int:
    source_pdf = (
        PROJECT_ROOT
        / "evaluation"
        / "corpus"
        / "差旅报销制度_v1.pdf"
    )

    if not source_pdf.is_file():
        raise FileNotFoundError(
            f"测试 PDF 不存在: {source_pdf}"
        )

    app = create_app()

# - **`TestClient(app)`**：FastAPI 自带的测试客户端（底层基于 httpx 库），作用是把我们创建的 FastAPI 应用实例包装成一个可本地调用的 HTTP 客户端。
#   - 不需要启动 uvicorn 等真实服务器，进程内直接调用接口，执行速度极快，非常适合自动化测试；
#   - 请求行为、参数格式和真实 HTTP 客户端完全一致，服务端代码无感知。
# - **`with ... as client:`**：用上下文管理器管理测试客户端的生命周期，测试代码执行完后自动释放客户端资源，无需手动关闭。
# - **`client`**：测试客户端实例，后续通过它调用 `get`/`post` 等方法发起请求。
    with TestClient(app) as client:
        # 层级	字段	含义	对应服务端的位置
        # 字典键	"file"	上传表单的字段名，必须和接口定义的参数名完全一致	对应接口 upload_document(file: UploadFile = File(...)) 里的参数名 file
        # 三元组第 1 位	source_pdf.name	告诉服务端「上传的文件叫什么名字」	对应服务端 file.filename
        # 三元组第 2 位	file	实际的文件二进制流，包含文件内容	对应服务端 file.file 文件流
        # 三元组第 3 位	"application/pdf"	文件的 MIME 类型，声明这是 PDF 文件	可选但推荐，服务端可用来做格式校验
        with source_pdf.open("rb") as file:
            response = client.post(
                "/documents/upload",
                files={
                    "file": (
                        source_pdf.name,
                        file,
                        "application/pdf",
                    )
                },
            )

    payload = response.json()

    passed = (
        response.status_code == 200
        and payload["filename"]
        == source_pdf.name
        and payload["source"]
        == source_pdf.name
        and payload["indexed_chunks"] > 0
        and payload["status"] == "indexed"
    )

    output = {
        "status_code": response.status_code,
        "response": payload,
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