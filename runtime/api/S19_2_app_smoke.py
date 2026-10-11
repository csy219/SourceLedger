import json
import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# 导入测试核心依赖：

# - `TestClient`：FastAPI 内置的测试客户端，基于 httpx，可在进程内直接调用 FastAPI 应用，**无需启动真实 HTTP 服务**，测试速度快，适合自动化测试。
# - `create_app`：API 应用创建工厂函数，用于创建待测试的 FastAPI 应用实例。
from fastapi.testclient import TestClient

from runtime.api.S19_2_app import create_app

def main() -> int:
    # 2.1 创建测试应用与客户端
    app = create_app()

    # - **`with TestClient(app) as client`**：创建测试客户端上下文管理器。
    # - `TestClient(app)`：包装目标应用，模拟 HTTP 客户端；
    # - `with` 语法保证测试结束后自动清理客户端资源；
    # - **变量 `client`**：测试客户端实例，用于发送 HTTP 请求。
    # - **变量 `health_response`**：`/health` 接口的响应对象，包含 HTTP 状态码、响应头、响应体等完整响应信息。
    # - `client.get("/health")`：向健康接口发送 GET 请求。
    # - **变量 `ready_response`**：`/ready` 接口的响应对象，同理包含完整的响应信息。
    # - `client.get("/ready")`：向就绪接口发送 GET 请求。
    with TestClient(app) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")

    # 2.2 解析响应体
    # - **变量 `health_payload`**：健康接口响应体解析后的字典，包含 `status`、`service`、`version` 字段。
    # - `.json()`：将响应体的 JSON 字符串解析为 Python 字典。
    # - **变量 `ready_payload`**：就绪接口响应体解析后的字典，包含 `ready`、`database`、`redis`、`details` 字段。
    health_payload = health_response.json()
    ready_payload = ready_response.json()


    # 2.3 测试通过条件判定
    # **变量 `passed`**：布尔值，标记整体测试是否通过，**6 项条件全部满足才为 True**。
    # 1. 健康接口 HTTP 状态码必须为 200（请求成功）；
    # 2. 就绪接口 HTTP 状态码必须为 200（服务就绪，若依赖不可用会返回 503）；
    # 3. 健康接口响应体的 `status` 字段必须为 `ok`；
    # 4. 就绪接口响应体的 `ready` 字段必须为 `True`（整体就绪）；
    # 5. 就绪接口的 `database` 字段必须为 `True`（数据库连通正常）；
    # 6. 就绪接口的 `redis` 字段必须为 `True`（Redis 连通正常）。
    passed = (
        health_response.status_code == 200
        and ready_response.status_code == 200
        and health_payload["status"] == "ok"
        and ready_payload["ready"] is True
        and ready_payload["database"] is True
        and ready_payload["redis"] is True
    )

    output = {
        "health_status_code": (
            health_response.status_code
        ),
        "health": health_payload,
        "ready_status_code": (
            ready_response.status_code
        ),
        "readiness": ready_payload,
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


### 三、核心设计总结

# 1. **进程内测试**：基于 `TestClient` 实现无需启动 HTTP 服务的接口测试，执行速度快，无端口占用，天然适合 CI 自动化流水线。
# 2. **全维度校验**：同时校验 HTTP 状态码和响应体字段，既验证协议层正确性，也验证业务逻辑正确性。
# 3. **结构化输出**：完整输出状态码、响应体、整体结果，测试失败时可直接通过输出定位问题。
# 4. **CI 友好**：通过整数退出码标识测试结果，可直接作为流水线门禁，失败时自动阻断后续流程