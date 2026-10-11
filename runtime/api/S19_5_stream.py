# 这是 **Agent Runtime 的流式问答接口模块**，基于 **SSE（Server-Sent Events，服务器推送事件）** 协议实现回答的逐段流式输出（类似打字机效果）。
# 核心特点是**100% 复用已有的问答核心执行逻辑**（幂等校验、状态持久化、异常兜底全部生效），
# 仅在输出层做流式封装，通过标准化的事件流协议推送「开始 - 文本块 - 引用 - 结束 - 错误」五类事件。


import json

# - `APIRouter`：FastAPI 路由类，用于模块化注册流式接口，和普通问答接口同属 runtime 分组。
# - `Request`：FastAPI 请求对象，用于访问应用全局状态（`app.state`），传递给核心执行函数
from fastapi import (
    APIRouter,
    Request,
)
# `StreamingResponse`：FastAPI 流式响应类，是实现 SSE 的核心载体；它接收一个生成器作为数据源，**边生成边发送**，不需要等全部内容生成完再一次性返回。
from fastapi.responses import StreamingResponse


# - `AskRequest`：复用统一的问答请求模型，保证流式接口和普通接口入参格式完全一致，客户端无需区分接口改参数。
from runtime.api.S19_1_schemas import (
    AskRequest,
)

# - `execute_ask`：导入普通问答接口的核心执行函数，**完整复用幂等校验、状态持久化、Agent 调用、异常兜底所有逻辑**，流式接口只做输出格式的转换，不重复实现业务逻辑。
from runtime.api.S19_4_routes import (
    execute_ask,
)

router=APIRouter(tags=["runtime"])


# 3. sse_event：SSE 标准事件构造函数
# - 函数作用：构造**符合 SSE 协议标准**的事件字符串，是流式输出的基础工具函数。
# - `event: str`：事件名称，比如 `start`、`token`、`done`，客户端可以根据事件名做不同处理。
# - `payload: dict`：事件携带的数据字典，会序列化为 JSON 放在 data 字段。
def sse_event(
    event:str,
    payload:dict,
)->str:
    # 返回标准 SSE 格式字符串，协议规则：

    # 1. `event: 事件名\n`：指定事件类型；
    # 2. `data: JSON字符串\n`：携带事件数据；
    # 3. **两个连续换行 `\n\n`**：标记一个事件结束，客户端的 EventSource 会以此为分隔解析事件。
    # - `ensure_ascii=False`：保证中文正常输出，不转义为 Unicode 编码。
    # > 补充：这是 SSE 的强制格式，浏览器原生 `EventSource` 对象可以自动识别和解析这种格式，逐事件触发回调。
    return (
        f"event: {event}\n"
        "data: "
        + json.dumps(
            payload,
            ensure_ascii=False,
        )
        + "\n\n"
    )

# 4. split_answer：回答文本拆分函数
# - 通过列表推导式按步长切片，返回字符串列表；
# - 说明：当前方案是**拿到完整回答后拆分模拟流式**，属于兼容方案；真正的流式生成是模型边生成边推送，无需拆分。
def split_answer(
    answer:str,
    chunk_size:int=12,
)->list[str]:
    return [
        answer[index:index+chunk_size]
        for index in range(
            0,
            len(answer),
            chunk_size
        )
    ]

# 5. stream_events：流式事件生成器（核心）
# - 函数作用：流式响应的核心生成器函数，作为 `StreamingResponse` 的数据源，通过 `yield` 逐个推送 SSE 事件。
# - 这是一个**生成器函数**（包含 `yield` 关键字），执行时不会一次性跑完，每次迭代到 `yield` 就暂停并返回数据，下次迭代再继续执行。
# - `request: Request`：请求对象，用于传递给 `execute_ask` 访问全局资源。
# - `payload: AskRequest`：客户端传入的问答请求参数。
def stream_events(
    request:Request,
    payload:AskRequest,
):

    # - **变量 `stream_request`**：复制后的请求对象，将 `stream` 字段强制更新为 `True`。
    # - `model_copy(update=...)` 是 Pydantic 的方法，复制实例并修改指定字段，不改动原始对象；
    # - 标记流式模式，供底层逻辑识别（当前版本核心逻辑无差异，预留扩展）。
    # - **变量 `response`**：`execute_ask` 返回的完整问答结果，类型为 `AskResponse`，包含回答、引用、任务 ID 等全部信息。
    # - 核心设计：**完整复用普通接口的所有业务逻辑**，幂等校验、状态持久化、异常兜底、检查点保存全部正常执行，和普通 `/ask` 接口行为完全一致，仅输出格式不同。
    try:
        stream_request=payload.model_copy(
            update={"stream":True}
        )
        response=execute_ask(request,stream_request)

        # 5.2 推送 start 开始事件
        # - 第一个事件，告诉客户端任务已开始；
        # - 携带任务 ID、线程 ID、是否幂等重放，客户端可以提前更新 UI、绑定任务标识。
        yield sse_event(
            "start",
            {
                "run_id":response.run_id,
                "thread_id":response.thread_id,
                "replayed":response.replayed,
            }
        )

        # 5.3 推送 token 文本块事件
        # - 遍历拆分后的文本块，逐个推送 `token` 事件；
        # - `delta` 字段表示「增量文本」，客户端收到后直接追加到回答末尾，就能实现打字机效果。
        for chunk in split_answer(
            response.answer
        ):
            yield sse_event(
                "token",
                {
                    "delta":chunk
                }
            )

        # 5.4 推送 citation 引用事件
        # - 遍历所有引用文献，逐个推送 `citation` 事件；
        # - `citation.model_dump()` 将引用对象转为字典，包含引用编号、来源、页码。
        for citation in response.citations:
            yield sse_event(
                "citation",
                citation.model_dump()
            )

        # 5.5 推送 done 结束事件
        # - 最后一个事件，告诉客户端整个流传输完成；
        # - 携带最终任务状态、任务 ID，客户端可以标记回答结束、更新状态。
        yield sse_event(
            "done",
            {
                "run_id":response.run_id,
                "status":response.status.value,
                "replayed":response.replayed,
                "context_tokens_est":response.context_tokens_est,
                "input_tokens":response.input_tokens,
                "output_tokens":response.output_tokens,
                "total_tokens":response.total_tokens,
                "cache_read_tokens":response.cache_read_tokens,
                "latency_ms":response.latency_ms
            }
        )

    # 5.6 异常兜底：推送 error 事件
    # - 捕获整个执行过程中的所有异常；
    # - 不直接抛出异常，而是推送一个 `error` 事件，包含错误类型和错误信息；
    # - 设计优势：保证客户端能收到结构化的错误，而不是连接直接断开，体验更友好，也便于客户端统一错误处理。
    except Exception as exc:
        yield sse_event(
            "error",
            {
                "error_type":type(exc).__name__,
                "message":str(exc),
            }
        )

# 6. ask_stream：流式问答接口
# 返回 `StreamingResponse` 流式响应对象，三个核心配置：

# 1. **内容源**：`stream_events(request, payload)` 生成器函数，FastAPI 会自动迭代这个生成器，每次 `yield` 就向客户端发送一段数据。
# 2. **媒体类型**：`text/event-stream`，SSE 的标准 MIME 类型，告诉客户端这是 SSE 事件流。
# 3. **响应头**：
#    - `Cache-Control: no-cache`：禁止缓存，保证每次都是实时数据，不会命中缓存旧内容；
#    - `Connection: keep-alive`：保持长连接，SSE 是基于 HTTP 长连接的单向推送，必须保持连接不断开。
@router.post(
    "/ask/stream"
)
def ask_stream(
    request:Request,
    payload:AskRequest,
):
    return StreamingResponse(
        stream_events(request, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

### 三、核心设计总结

# 1. **逻辑完全复用**：流式接口不重复实现问答业务，仅做输出层的格式转换，幂等、持久化、异常处理全部和普通接口对齐，维护成本低、行为一致。
# 2. **标准化事件协议**：按 SSE 标准拆分事件类型，客户端可以按事件做精细化处理（开始更新 ID、文本追加、引用渲染、结束标记、错误处理）。
# 3. **生成器流式输出**：通过 `yield` 实现逐块推送，无需等待完整回答生成，内存占用低，体验接近原生流式生成。
# 4. **异常友好处理**：异常转化为 error 事件推送，不直接断开连接，客户端可以统一捕获和展示错误。
# 5. **入参完全兼容**：和普通 `/ask` 接口使用相同的请求模型，客户端切换接口无需修改请求参数，成本极低。
