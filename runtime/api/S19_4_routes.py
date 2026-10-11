# 这是 **Agent Runtime 核心业务路由模块**，基于 FastAPI 路由化实现三大核心接口，同时深度集成数据库状态持久化、请求幂等、运行检查点机制，是连接 API 层与 Agent 核心能力的枢纽。
# 实现的三个接口：

# 1. `POST /sessions`：创建对话会话，生成唯一会话与线程标识
# 2. `POST /ask`：发起问答请求，带幂等保护、全流程状态持久化、异常兜底
# 3. `GET /tasks/{run_id}`：查询任务执行状态与进度


# - `import uuid`：Python 内置唯一标识生成模块，用于生成会话 ID、兜底请求 ID，保证全局唯一性。
# - `APIRouter`：FastAPI 路由类，用于模块化注册业务接口，与主应用解耦。
# - `HTTPException`：HTTP 异常类，用于抛出指定状态码的业务异常（如任务不存在 404）。
# - `Request`：FastAPI 请求对象，用于访问应用全局状态（`app.state`），获取数据库工厂、Agent 执行函数等全局资源。
import inspect
import uuid
from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)

from runtime.S15_state_reference import (
    RunState,
    RunStatus,
)
from runtime.api.S19_1_schemas import (
    AskRequest,
    AskResponse,
    CitationItem,
    CreateSessionRequest,
    CreateSessionResponse,
    TaskStatus,
    TaskStatusResponse,
)
from runtime.db.S16_3_run_repository import (
    RunStateRepository,
)
from runtime.db.checkpointer import (
    DatabaseCheckpointer,
)
from runtime.resilience.S17_5_idempotency import (
    RequestIdempotencyService,
)
from runtime.db.S16_4_idempotency_repository import (
    IdempotencyRepository,
)

from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import TraceStatus
from runtime.run_trace import (
    TraceDuplicateEventError,
)

router=APIRouter(tags=["runtime"])

# 3. get_repositories 仓库获取工具函数
# 函数作用：**请求级依赖提供者**，从请求的全局状态中取出数据库会话工厂，创建本次请求所需的所有业务组件，相当于轻量依赖注入。
def get_repositories(
    request:Request,
)->tuple[
    RunStateRepository,
    DatabaseCheckpointer,
    RequestIdempotencyService,
]:
    # **变量 `session_factory`**：数据库会话工厂，从应用全局状态中获取，是整个数据层的核心入口，用于创建数据库会话。
    session_factory=(
        request.app.state.session_factory
    )

    # 返回三个业务组件，都基于同一会话工厂创建，保证同一个请求内使用同一个数据库会话上下文：

    # 1. `RunStateRepository`：任务状态仓库，负责任务状态的读写。
    # 2. `DatabaseCheckpointer`：检查点持久化工具，负责状态落盘。
    # 3. `RequestIdempotencyService`：幂等服务，内部包装了幂等仓库，提供幂等执行能力。
    return (
        RunStateRepository(session_factory),
        DatabaseCheckpointer(session_factory),
        RequestIdempotencyService(
            IdempotencyRepository(
                session_factory
            )
        ),
    )

# 4. execute_ask 问答执行核心函数
# - 函数作用：问答请求的核心执行器，封装**幂等校验 → 状态初始化 → 执行 Agent → 状态更新 → 结果组装**全流程，是整个模块的业务核心。
# - `request: Request`：当前请求对象，用于访问全局资源。
# - `ask_request: AskRequest`：问答请求参数，包含问题、线程 ID、请求 ID 等。
def execute_ask(
    request:Request,
    ask_request:AskRequest
)->AskResponse:
    # 调用工具函数，获取本次请求所需的状态仓库、检查点、幂等服务三个组件。
    (
        run_repository,
        checkpointer,
        idempotency_service
    )=get_repositories(request)

    request_key=(ask_request.request_id or uuid.uuid4().hex)

    # 4.3 业务逻辑函数（幂等保护的核心执行块）
    def business_function()->dict:
        # 步骤 1：初始化任务状态
        # **变量 `state`**：任务运行状态实体。
        # - 调用 `RunState.create` 创建初始状态，绑定线程 ID、目标问题、最大执行步数 20；
        # - `run_repository.create(state)`：将初始状态存入数据库，任务持久化。
        state=RunState.create(
            thread_id=ask_request.thread_id,
            goal=ask_request.question,
            max_steps=20,
        )

        run_repository.create(state)

        # 步骤 2：更新为执行中状态并保存检查点
        state.status=RunStatus.RUNNING
        state.current_node="call_model"
        state.increment_step()

        checkpointer.save(state,node="call_model")

        # 步骤 3：调用 Agent 核心问答能力
        # - **变量 `raw_result`**：Agent 问答函数的原始返回结果，通常包含回答文本、引用列表等。
        # - `request.app.state.ask_function`：从全局状态取出的 Agent 问答执行函数，是真正的业务能力入口，由主应用启动时注入。
        try:
            ask_function = (
                request.app.state
                .ask_function
            )
            ask_parameters = (
                inspect.signature(
                    ask_function
                ).parameters
            )

            if "run_id" in ask_parameters:
                raw_result = ask_function(
                    ask_request.question,
                    ask_request.thread_id,
                    run_id=state.run_id,
                )
                trace_store = getattr(
                    request.app.state,
                    "trace_store",
                    None,
                )

                if trace_store is not None:
                    for event_data in (
                        raw_result.get(
                            "trace",
                            [],
                        )
                    ):
                        event = CapabilityEvent(
                            event_id=str(
                                event_data[
                                    "event_id"
                                ]
                            ),
                            run_id=state.run_id,
                            timestamp=(
                                event_data.get(
                                    "started_at"
                                )
                                or ""
                            ),
                            stage=str(
                                event_data["stage"]
                            ),
                            operation=str(
                                event_data[
                                    "operation"
                                ]
                            ),
                            status=TraceStatus(
                                event_data["status"]
                            ),
                            attempt=int(
                                event_data.get(
                                    "attempt",
                                    1,
                                )
                            ),
                            action=str(
                                event_data.get(
                                    "action",
                                    "",
                                )
                            ),
                            duration_ms=float(
                                event_data.get(
                                    "duration_ms",
                                    0.0,
                                )
                            ),
                            metadata=dict(
                                event_data.get(
                                    "metadata",
                                    {},
                                )
                            ),
                        )

                        try:
                            trace_store.append_event(
                                event
                            )
                        except (
                            TraceDuplicateEventError
                        ):
                            pass
                
            else:
                raw_result = ask_function(
                    ask_request.question,
                    ask_request.thread_id,
                )
                trace_store = getattr(
                    request.app.state,
                    "trace_store",
                    None,
                )

                if trace_store is not None:
                    for event_data in (
                        raw_result.get(
                            "trace",
                            [],
                        )
                    ):
                        event = CapabilityEvent(
                            event_id=str(
                                event_data[
                                    "event_id"
                                ]
                            ),
                            run_id=state.run_id,
                            timestamp=(
                                event_data.get(
                                    "started_at"
                                )
                                or ""
                            ),
                            stage=str(
                                event_data["stage"]
                            ),
                            operation=str(
                                event_data[
                                    "operation"
                                ]
                            ),
                            status=TraceStatus(
                                event_data["status"]
                            ),
                            attempt=int(
                                event_data.get(
                                    "attempt",
                                    1,
                                )
                            ),
                            action=str(
                                event_data.get(
                                    "action",
                                    "",
                                )
                            ),
                            duration_ms=float(
                                event_data.get(
                                    "duration_ms",
                                    0.0,
                                )
                            ),
                            metadata=dict(
                                event_data.get(
                                    "metadata",
                                    {},
                                )
                            ),
                        )

                        try:
                            trace_store.append_event(
                                event
                            )
                        except (
                            TraceDuplicateEventError
                        ):
                            pass
        # - 捕获执行过程中的所有异常；
        # - 将任务状态更新为 `FAILED`，节点标记为 `failed`，再次保存检查点，保证失败状态可追溯；
        # - 抛出包装后的运行时异常，保留原始异常堆栈，同时向上层传递失败信息。
        except Exception as exc:
            state.status=RunStatus.FAILED
            state.current_node="failed"
            checkpointer.save(state,node="failed")
            raise RuntimeError(
                f"Agent 问答失败: {exc}"
            )from exc

        # 步骤 5：引用格式转换
        # **变量 `citations`**：标准化的引用列表，类型为 `list[CitationItem]`。
        # - 将 Agent 返回的原始引用字典，转换成 API 层标准的 `CitationItem` 模型；
        # - `enumerate(..., start=1)`：编号从 1 开始，对应 `C1`、`C2` 标准引用格式；
        # - `raw_result.get("citations", [])`：安全获取引用列表，不存在则返回空列表，避免报错。
        citations=[
            CitationItem(
                citation_id=f"C{index}",
                source=str(item["source"]),
                page=int(item["page"])
            )
            for index,item in enumerate(
                raw_result.get("citations",[]),
                start=1,
            )
        ]

        # 步骤 6：更新为完成状态并保存检查点
        state.status = RunStatus.COMPLETED
        state.current_node = "finish"
        checkpointer.save(
            state,
            node="finish",
        )

        # 步骤 7：组装响应并返回
        # - **变量 `response`**：标准化问答响应对象，填充任务 ID、线程 ID、状态、回答、引用等字段；
        # - `response.model_dump(mode="json")`：将 Pydantic 模型转换为可 JSON 序列化的字典，供幂等服务存储和返回。
        response = AskResponse(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=TaskStatus.COMPLETED,
            answer=str(raw_result["answer"]),
            citations=citations,
            context_tokens_est=int(
                raw_result.get("context_tokens_est",0)
            ),
            input_tokens=int(
                raw_result.get("input_tokens",0)
            ),
            output_tokens=int(
                raw_result.get("output_tokens",0)
            ),
            total_tokens=int(
                raw_result.get("total_tokens",0)
            ),
            cache_read_tokens=int(
                raw_result.get("cache_read_tokens",0)
            ),
            latency_ms=raw_result.get("latency_ms",0.0),
            replayed=False,
        )
        return response.model_dump(
            mode="json"
        )


    # 4.4 幂等执行
    # - **变量 `idempotency_result`**：幂等服务的执行结果，包含 `value`（执行结果）和 `replayed`（是否为重放）两个属性。
    # - `idempotency_service.execute(...)`：幂等执行入口：
    # - 第一次请求：执行 `business_function`，存储结果，返回结果 + `replayed=False`；
    # - 重复请求：直接返回历史存储的结果，`replayed=True`，不执行业务逻辑。
    idempotency_result = (
        idempotency_service.execute(
            key=request_key,
            run_id=ask_request.thread_id,
            func=business_function,
        )
    )

    # 4.5 结果组装返回
    # - `AskResponse.model_validate(...)`：将幂等服务返回的字典，重新验证并实例化为 `AskResponse` 对象，保证类型正确；
    # - `response.replayed`：标记本次结果是首次执行还是重放，客户端可以据此判断是否命中幂等；
    # - 返回最终的标准化响应对象。
    response = AskResponse.model_validate(
        idempotency_result.value
    )
    response.replayed = (
        idempotency_result.replayed
    )
    return response


# 5. POST /sessions 创建会话接口
# - 接口作用：创建新的对话会话，生成唯一的会话标识与线程标识，用于后续问答关联上下文。
# - `payload: CreateSessionRequest`：入参，包含用户 ID、会话标题，自动做参数校验
@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
)
def create_session(
    payload: CreateSessionRequest,
) -> CreateSessionResponse:
    session_id = uuid.uuid4().hex

    return CreateSessionResponse(
        session_id=session_id,
        thread_id=f"session:{session_id}",
        user_id=payload.user_id,
        status="created",
    )


# 6. POST /ask 问答接口
# - 接口作用：核心问答入口，接收用户问题，触发 Agent 执行，返回回答与引用，自带幂等与状态持久化。
# - `request: Request`：请求对象，用于访问全局资源；
# - `payload: AskRequest`：问答请求参数，自动做长度、格式校验。
@router.post(
    "/ask",
    response_model=AskResponse,
)
def ask_question(
    request:Request,
    payload:AskRequest,
)->AskResponse:
    return execute_ask(request,payload)

# 7. GET /tasks/{run_id} 任务状态查询接口
# - 接口作用：查询指定任务的执行状态、进度、当前节点，用于异步场景的轮询查询。
# - `run_id: str`：路径参数，任务执行 ID，对应问答请求返回的 `run_id`。
@router.get(
    "/tasks/{run_id}",
    response_model=TaskStatusResponse,
)
def get_task_status(
    request:Request,
    run_id:str,
)->TaskStatusResponse:
    session_factory=request.app.state.session_factory
    repository=RunStateRepository(session_factory)

    # **变量 `summary`**：任务状态摘要对象，包含任务的核心状态字段（不含冗余信息）。
    # - `repository.get_summary(run_id)`：根据任务 ID 查询状态摘要，不存在则返回 `None`
    summary=repository.get_summary(run_id)

    # 任务不存在时，抛出 404 异常，返回任务不存在的提示，符合 RESTful 规范。
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"任务不存在: {run_id}"
        )

    # - 将数据库查询的摘要对象，转换为 API 层标准的 `TaskStatusResponse` 模型返回；
    # - `TaskStatus(summary.status.value)`：将内部状态枚举转换为 API 层状态枚举，做一层适配，避免内部状态直接暴露。
    return TaskStatusResponse(
        run_id=summary.run_id,
        thread_id=summary.thread_id,
        status=TaskStatus(
            summary.status.value
        ),
        current_node=summary.current_node,
        step_count=summary.step_count,
        max_steps=summary.max_steps,
    )


### 三、核心设计总结

# 1. **分层解耦**：API 层、业务执行层、数据仓库层分层清晰，接口只做协议适配，核心逻辑收敛到 `execute_ask` 统一管理。
# 2. **全链路状态持久化**：通过检查点机制在任务关键节点（开始、执行中、成功、失败）持久化状态，故障可追溯、可恢复。
# 3. **原生幂等支持**：基于请求 ID 实现幂等，重复请求不会重复执行业务，避免重复计费、重复执行副作用。
# 4. **统一异常兜底**：执行异常时自动更新失败状态并持久化，保证任务状态最终一致，不会出现 “悬挂” 任务。
# 5. **全局资源注入**：通过 `app.state` 注入数据库工厂、Agent 执行函数，路由层不硬编码依赖，可灵活替换与扩展。
    
