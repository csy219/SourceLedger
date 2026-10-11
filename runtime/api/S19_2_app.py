# 这是 **Agent Runtime 服务的 API 入口与服务生命周期管理模块**，基于 FastAPI 构建，核心能力包括：

# 1. 服务生命周期管理：启动时自动初始化数据库连接池、Redis 客户端，关闭时自动释放资源
# 2. 健康检查接口：提供基础存活探测接口
# 3. 就绪检查接口：深度校验数据库、Redis 两大核心依赖的连通性，未就绪时返回 503 状态码
# 4. 全局资源共享：将数据库引擎、Redis 客户端挂载到应用状态，供全应用路由调用


# `import os`：Python 系统操作模块，用于读取环境变量，获取 Redis 连接地址
import os

# `from contextlib import asynccontextmanager`：异步上下文管理器装饰器，用于定义 FastAPI 的生命周期钩子，实现**服务启动初始化资源、服务停止释放资源**的逻辑。
from contextlib import asynccontextmanager

# `from typing import Any`：类型注解工具，表示任意数据类型，提升代码可读性
from typing import Any

# - `FastAPI`：FastAPI 框架核心类，用于创建 Web 应用实例。
# - `Request`：FastAPI 请求对象，用于访问请求上下文、应用状态等。
# - `Response`：FastAPI 响应对象，用于动态修改响应状态码、响应头等。
# - `status`：FastAPI 内置的 HTTP 状态码常量集合，避免硬编码数字，提升可读性。
from fastapi import (
    FastAPI,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

# `Redis`：Redis 客户端类，用于创建 Redis 连接、执行 Redis 命令。
from redis import Redis

# `text`：SQLAlchemy 的原生 SQL 包装函数，用于将字符串包装为可执行的 SQL 语句。
from sqlalchemy import text

from runtime.api.S19_1_schemas import (
    HealthResponse,
    ReadinessResponse,
)
from runtime.db.config import DatabaseConfig
from runtime.db.engine import (
    create_db_engine,
)

from runtime.api.S19_3_documents import (
    router as documents_router,
)


from runtime.api.S19_4_routes import (
    router as runtime_router,
)
from runtime.db.engine import (
    create_session_factory,
)


from runtime.api.S19_5_stream import (
    router as stream_router,
)
from runtime.api.capabilities import (
    CapabilityRegistry,
    capability_registry,
    create_capabilities_router,
)
from runtime.run_trace import (
    InMemoryTraceStore,
    TraceStore,
)
from runtime.capabilities import (
    register_default_capabilities,
)

# 1. 修改 S19_2_app.py，支持注入测试问答函数
# 顶部的 typing 导入增加 Callable：
from typing import Any, Callable

# 2. get_redis_url Redis 地址获取函数
# - 函数作用：获取 Redis 服务的连接 URL，优先读取环境变量，未配置时使用默认本地地址。
# - `os.getenv("REDIS_URL", "redis://localhost:6380/0")`：
#   - 从系统环境变量中读取 `REDIS_URL`；
#   - 第二个参数为默认值，环境变量不存在时返回该值；
#   - 默认地址为本地 6380 端口的 0 号数据库。
def get_redis_url()->str:
    return os.getenv(
        "REDIS_URL",
        "redis://localhost:6380/0",
    )



# 3. lifespan 应用生命周期管理器
# - 函数作用：FastAPI 应用的异步生命周期钩子，分为**启动阶段**和**关闭阶段**，管理全局资源的初始化与销毁。
# - `@asynccontextmanager`：将异步函数包装为异步上下文管理器，配合 FastAPI 的 `lifespan` 参数使用。
# - `app: FastAPI`：入参，FastAPI 应用实例，用于挂载全局资源。
@asynccontextmanager
async def lifespan(
    app:FastAPI,
):
    # 启动阶段：资源初始化
    # - `database_config`：数据库配置对象，通过 `from_env()` 从环境变量加载数据库连接信息。
    # - `engine`：SQLAlchemy 数据库引擎（连接池），是数据库操作的核心入口，所有数据库查询都通过该引擎执行。
    # - `redis`：Redis 客户端实例；
    # - `Redis.from_url()`：通过 URL 字符串创建 Redis 连接；
    # - `decode_responses=True`：自动将 Redis 返回的字节结果解码为字符串，避免手动转码。
    database_config=DatabaseConfig.from_env()
    engine=create_db_engine(database_config)
    app.state.session_factory = (
            create_session_factory(engine)
        )
    
    # 这段代码一般放在 **FastAPI 应用的 lifespan 启动钩子**中，作用是初始化全局的问答核心函数 `app.state.ask_function`，核心逻辑是「优先用外部注入的覆盖实现，没有就加载默认的真实 Agent 实现」。
    # - 这是 Python 内置的**安全属性读取函数`getattr`**，语法为 `getattr(对象, 属性名, 默认值)`
    # - 含义：从全局状态对象 `app.state` 上，尝试读取名为 `ask_function_override` 的属性；
    # - 如果这个属性存在，就把它的值赋给变量 `override`；
    # - 如果这个属性不存在，不会抛出`AttributeError`异常，而是返回默认值 `None`。
    # - 本质：这是一个**约定好的扩展钩子**，外部可以提前往`app.state`上挂载这个属性，来覆盖默认实现。
    override=getattr(
        app.state,
        "ask_function_override",
        None,
    )
    if override is not None:
        app.state.ask_function = override
    else:
        from runtime.ask_service import (
            ask as runtime_ask,
        )

        app.state.ask_function = (
            runtime_ask
        )
        
    redis=Redis.from_url(
        get_redis_url(),
        decode_responses=True,
    )

    # - `app.state`：FastAPI 内置的**应用级状态容器**，用于存储全局共享资源；
    # - 将数据库引擎和 Redis 客户端挂载到应用状态后，所有路由都可以通过 `request.app.state` 访问这些资源，无需重复创建连接。
    app.state.engine=engine
    app.state.redis=redis

    # 运行阶段：服务对外提供服务
    # `yield` 是上下文管理器的分界点：
    # - `yield` 之前的代码在**服务启动时**执行（资源初始化）；
    # - `yield` 处暂停，服务正常运行，接收处理请求；
    # - `yield` 之后的代码在**服务停止时**执行（资源清理）。
    try:
        yield
    # 关闭阶段：资源释放
    # - `finally` 保证无论服务正常停止还是异常终止，都会执行资源清理；
    # - `redis.close()`：关闭 Redis 连接，释放网络资源；
    # - `engine.dispose()`：销毁数据库连接池，关闭所有数据库连接。
    finally:
        redis.close()
        engine.dispose()
    

# 4. create_app 应用创建函数
# - `app`：FastAPI 应用实例；
# - `title`：API 文档标题，会显示在自动生成的 OpenAPI 文档页面；
# - `version`：API 版本号；
# - `lifespan=lifespan`：指定使用上面定义的生命周期管理器，接管应用的启动与关闭流程。
def create_app(
    ask_function: Callable[..., Any] | None = None,
    trace_store: TraceStore | None = None,
    capabilities: CapabilityRegistry | None = None,
) -> FastAPI:
    app=FastAPI(
        title="SourceLedger API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.ask_function_override=ask_function

    app.state.trace_store = (
        trace_store
        if trace_store is not None
        else InMemoryTraceStore()
    )

    app.include_router(documents_router)

    app.include_router(runtime_router)

    app.include_router(stream_router)

    active_registry = (
        capabilities
        if capabilities is not None
        else capability_registry
    )

    if capabilities is None:
        register_default_capabilities(active_registry)

    app.include_router(
        create_capabilities_router(
            active_registry
        )
    )

    # 4.1 /health 健康检查接口
    # - `@app.get("/health")`：注册 GET 方法的 `/health` 路由；
    # - `response_model=HealthResponse`：指定响应数据模型，FastAPI 会自动做类型校验和 JSON 序列化，同时生成接口文档。
    # - 接口作用：基础存活探测，只要服务进程正常就返回 `ok`，用于监控系统判断服务是否存活。
    # - 返回内容：状态为 `ok`，服务名 `source-ledger`，版本号 `0.1.0`。
    @app.get(
        "/health",
        response_model=HealthResponse,
    )
    def health()->HealthResponse:
        return HealthResponse(
            status="ok",
            service="source-ledger",
            version="0.1.0",
        )


    # 4.2 /ready 就绪检查接口
    # - 接口作用：深度就绪探测，校验数据库、Redis 两大核心依赖是否正常可用，用于判断服务是否可以接收业务流量。
    # - `request: Request`：请求对象，用于访问应用状态中的全局资源。
    # - `response: Response`：响应对象，用于动态修改 HTTP 状态码。
    @app.get(
        "/ready",
        response_model=ReadinessResponse,
    )
    def readiness(
        request:Request,
        response:Response,
    )->ReadinessResponse:
        engine=request.app.state.engine
        redis=request.app.state.redis

        details: dict[str, str] = {}
        database_ok = False
        redis_ok = False

        # 步骤 3：数据库连通性校验
        # - `with engine.connect() as connection`：从连接池中取出一个数据库连接，`with` 语法保证使用完自动归还连接到连接池。
        # - `connection.scalar(text("SELECT 1"))`：执行原生 SQL `SELECT 1`，返回单个标量结果；这是数据库连通性校验的标准做法，只验证连接和执行能力，不涉及业务数据。
        # - `database_ok = value == 1`：查询结果等于 1 说明数据库正常，标记为就绪。
        # - 正常时 `details` 记录 `ok`，结果异常记录 `bad_result`；
        # - 捕获所有异常时，`details` 记录错误类型名称（如 `OperationalError`），不抛出异常，保证接口始终返回结构化响应。
        try:
            with engine.connect() as connection:
                value=connection.scalar(
                    text("SELECT 1")
                )
                database_ok=value==1
                details["database"]=(
                    "ok" if database_ok else "bad_result"
                )
        except Exception as exc:
            details["database"]=f"error:{type(exc).__name__}"

        # 步骤 4：Redis 连通性校验
        # - `redis.ping()`：Redis 标准连通性命令，连接正常时返回 `True`；
        # - 同样做异常捕获，将错误类型记录到 `details` 中。
        try:
            redis_ok=bool(redis.ping())
            details["redis"]=(
                "ok" if redis_ok else "bad_result"
            )
        except Exception as exc:
            details["redis"]=f"error:{type(exc).__name__}"

        # 步骤 5：就绪判断与状态码设置
        # - `ready`：整体就绪标记，**数据库和 Redis 都正常才判定为就绪**。
        # - 未就绪时，将响应状态码设置为 `503 Service Unavailable`；这是就绪检查的标准规范，负载均衡器、K8s 等编排系统会根据 503 状态码判断该实例不能接入流量。
        ready=database_ok and redis_ok
        if not ready:
            response.status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return ReadinessResponse(
            ready=ready,
            database=database_ok,
            redis=redis_ok,
            details=details,
        )

    return app
app=create_app()
