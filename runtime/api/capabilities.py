# 这是整个 RAG 系统的**标准化能力框架 + HTTP API 层**，相当于给你之前学的所有业务模块（重写、检索、融合、生成、追踪）套上一层「统一外壳」：
# 把所有功能都封装成标准化的「能力（Capability）」，统一注册、统一执行、自动全链路追踪，再通过 FastAPI 对外暴露成标准 HTTP 接口。
# 简单说：**之前是零散的模块，现在做成了可插拔、可调用、可追踪、有 API 的标准化服务**。

# 下面逐层拆解，结合你之前学的追踪、存储、并发等知识点串起来。

# ---

# ## 一、整体定位与核心目标

# ### 解决的问题

# 在这之前，各个业务模块（B02~B08）是零散的，每个功能要单独写接口、单独写错误处理、单独加追踪逻辑，重复工作多、格式不统一、排障麻烦。

# ### 这个框架做的事

# 1. **统一能力规范**：所有功能都按同一个标准定义，输入、输出、错误、追踪格式完全一致
# 2. **自动全链路追踪**：任何能力执行，自动记录开始 / 结束 / 失败事件，业务内部还可以追加子事件，整条链路自动串起来
# 3. **统一 API 入口**：所有能力都通过同一套 HTTP 接口调用，不用每个功能单独写路由
# 4. **可插拔扩展**：加新功能，只需要写业务逻辑，注册一下，自动获得接口、追踪、错误处理、监控能力

# ### 和之前模块的关系

# - 复用你之前学的 `TraceStore` / `TraceRecorder` 追踪存储体系
# - 复用 `CapabilityEvent` 标准事件模型
# - 业务逻辑（问答、检索、重写等）作为「能力处理器」注册进来
# - 对外输出标准 HTTP 接口

"""Capability registry and FastAPI routes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
)
from uuid import uuid4

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from runtime.capability_events import (
    CapabilityEvent,
)
from runtime.rag_contracts import TraceStatus
from runtime.run_trace import (
    TraceNotFoundError,
    TraceRecorder,
    TraceStore,
)

### 第一层：数据模型（标准化契约）
# 全部基于 Pydantic，做接口数据校验，保证输入输出格式统一。
#          模型	                       作用	                                  类比
# CapabilityDescriptor	能力的「说明书」：ID、名称、描述、分类、标签、是否启用	应用商店的应用介绍页
# CapabilityRunRequest	调用能力的统一请求体：输入参数、run_id、线程 ID	统一的下单格式
# CapabilityRunResponse	调用能力的统一响应：run_id、状态、输出、事件数、耗时	统一的回执单
# RunTraceResponse	查询链路追踪的响应：完整事件列表、创建 / 更新时间	行车记录仪回放
# CapabilityExecutionError	标准化执行错误：携带能力 ID、run_id、错误信息	统一的错误通知单
# CapabilityHandler	能力处理函数的类型契约：输入 = 请求 + 追踪记录器，输出 = 结果字典	能力的「插座标准」
class CapabilityDescriptor(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    capability_id: str = Field(
        min_length=1
    )
    name: str = Field(
        min_length=1
    )
    description: str = Field(
        min_length=1
    )
    category: str = Field(
        min_length=1
    )
    tags: list[str] = Field(
        default_factory=list
    )
    enabled: bool = True


class CapabilityRunRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    input: dict[str, Any] = Field(
        default_factory=dict
    )
    run_id: str | None = None
    thread_id: str = "default"


class CapabilityRunResponse(BaseModel):
    run_id: str
    capability_id: str
    status: str
    output: dict[str, Any] = Field(
        default_factory=dict
    )
    event_count: int = 0
    latency_ms: float = 0.0



class RunTraceResponse(BaseModel):
    run_id: str
    event_count: int
    events: list[dict[str, Any]]
    created_at: str
    updated_at: str



class CapabilityExecutionError(RuntimeError):
    def __init__(
        self,
        capability_id: str,
        run_id: str,
        message: str,
    ) -> None:
        super().__init__(
            f"{capability_id} 执行失败: "
            f"{message}"
        )
        self.capability_id = capability_id
        self.run_id = run_id
        self.message = message


CapabilityHandler = Callable[
    [
        CapabilityRunRequest,
        TraceRecorder,
    ],
    dict[str, Any],
]

# 第二层：`CapabilityDefinition` —— 能力定义
# **一个完整的能力 = 「它是什么」 + 「它怎么执行」**
# - `descriptor`：描述信息，给人看、给列表接口用
# - `handler`：真正的业务处理函数，执行具体功能

# > 例子：
# > - descriptor：「能力 ID：rag_ask，名称：RAG 问答，描述：基于知识库回答问题」
# > - handler：真正调用 RAGRuntime 跑完整链路的函数
@dataclass(frozen=True)
class CapabilityDefinition:
    descriptor: CapabilityDescriptor
    handler: CapabilityHandler



# 第三层：`CapabilityRegistry` —— 能力注册中心
# 整个框架的核心调度器，相当于「能力管理器 + 执行调度器」，内部维护一个能力字典
#      Run流程:
# 1. 查到对应的能力定义
# 2. 生成 run_id（用户没传就自动生成UUID）
# 3. 创建 TraceRecorder，绑定传入的 trace_store（就是你之前学的追踪存储）
# 4. 自动记录「能力开始」事件（STARTED），带上分类、输入参数等元数据
# 5. 调用真正的业务处理函数，把 recorder 传进去
#    → 业务函数内部可以用 recorder 追加各个子阶段的事件
# 6. 成功：
#    → 自动记录「能力完成」事件（SUCCEEDED），带上耗时、输出信息
#    → 组装标准化响应返回
# 7. 失败：
#    → 自动记录「能力失败」事件（FAILED），带上错误信息
#    → 抛出标准化的 CapabilityExecutionError
class CapabilityRegistry:
    def __init__(self)->None:
        self._definitions:dict[str,CapabilityDefinition]={}

    ##### 1. `register()` —— 注册能力
    # - 把能力定义存进字典
    # - 重复 ID 直接报错，保证唯一
    def register(self,definition:CapabilityDefinition)->None:
        capability_id=definition.descriptor.capability_id

        if capability_id in self._definitions:
            raise ValueError(
                "diplicate capability_id: "
                f"{capability_id}"
            )

        self._definitions[capability_id]=definition

    # ##### 2. `get()` —— 获取能力
    # - 按 ID 查能力，不存在抛错
    def get(self,capability_id:str)->CapabilityDefinition:
        definition=self._definitions.get(capability_id)

        if definition is None:
            raise KeyError(capability_id)
        return definition

    # ##### 3. `list_descriptors()` —— 列出所有能力
    # - 返回所有能力的描述符，用于接口查询能力列表
    def list_descriptors(self)->list[CapabilityDefinition]:
        return[
            definition.descriptor
            for definition in sorted(
                self._definitions.values(),
                key=lambda item:(
                    item.descriptor.capability_id
                ),
            )
        ]
    # ##### 4. `run()` —— 执行能力（核心中的核心）
    # **这是整个框架的灵魂：自动把追踪和执行绑定，不用业务代码写任何事件逻辑。*
    def run(
        self,
        capability_id:str,
        request:CapabilityRunRequest,
        trace_store:TraceStore,
    )->CapabilityRunRequest:
        definition=self.get(capability_id)
        run_id=request.run_id or f"cap-{uuid4().hex}"
        recorder=TraceRecorder(trace_store)
        started=time.perf_counter()

        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:"
                    f"{capability_id}:start"
                ),
                run_id=run_id,
                stage="capability",
                operation=capability_id,
                status=TraceStatus.STARTED,
                action="start",
                metadata={
                    "category": (
                        definition
                        .descriptor.category
                    ),
                    "input_keys": sorted(
                        request.input
                    ),
                    "thread_id": (
                        request.thread_id
                    ),
                },
            )
        )
        try:
            run_request=request.model_copy(
                update={
                    "run_id":run_id
                }
            )
            output=definition.handler(
                run_request,
                recorder
            )
        except Exception as exc:
            latency_ms = round(
                (
                    time.perf_counter()
                    - started
                )
                * 1000,
                2,
            )
            recorder.append(
                CapabilityEvent(
                    event_id=(
                        f"{run_id}:"
                        f"{capability_id}:failed"
                    ),
                    run_id=run_id,
                    stage="capability",
                    operation=capability_id,
                    status=TraceStatus.FAILED,
                    action=type(exc).__name__,
                    duration_ms=latency_ms,
                    metadata={
                        "error": str(exc),
                    },
                )
            )
            raise CapabilityExecutionError(
                capability_id=capability_id,
                run_id=run_id,
                message=str(exc),
            ) from exc

        latency_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            2,
        )
        recorder.append(
            CapabilityEvent(
                event_id=(
                    f"{run_id}:"
                    f"{capability_id}:finished"
                ),
                run_id=run_id,
                stage="capability",
                operation=capability_id,
                status=TraceStatus.SUCCEEDED,
                action="finish",
                duration_ms=latency_ms,
                metadata={
                    "output_keys": sorted(
                        output
                    ),
                },
            )
        )
        trace = trace_store.get_run(run_id)

        return CapabilityRunResponse(
            run_id=run_id,
            capability_id=capability_id,
            status="succeeded",
            output=output,
            event_count=trace.event_count,
            latency_ms=latency_ms,
        )
    def has(
        self,
        capability_id: str,
    ) -> bool:
        return (
            capability_id
            in self._definitions
        )

### 第四层：`create_capabilities_router` —— FastAPI 路由层

# 把注册中心的能力，暴露成标准的 HTTP 接口，对外提供服务。
# 一共 3 个接口，对应三个核心操作：
# 接口	方法	作用
# /capabilities	GET	列出所有可用能力的描述，相当于「能力清单」
# /capabilities/{capability_id}/run	POST	调用执行某个能力，传入参数，返回执行结果
# /runs/{run_id}/trace	GET	根据 run_id 查询整条请求的完整追踪链路，排障用
def create_capabilities_router(
        registry:CapabilityRegistry,
)->APIRouter:
    router=APIRouter(tags=["capabilities"])

    # 1. **trace_store 从哪里来？**
    # 从 `request.app.state.trace_store` 取，也就是 FastAPI 应用启动时，全局初始化好的追踪存储实例（可以是内存版，也可以是数据库版）。
    # 👉 这里就呼应了之前的 `TraceStore` Protocol：因为定义了接口，所以不管是内存实现还是数据库实现，都能直接塞进来用，路由层代码不用改。
    # 2. **错误处理标准化**
    # - 能力不存在 → 404
    # - 执行失败 → 500，返回结构化错误信息（能力 ID、run_id、错误详情）
    # - 追踪不存在 → 404
    # 3. **和之前的并发、锁是什么关系？**
    # FastAPI 每个请求会开一个线程处理，也就是**多线程并发调用**。
    # 而 trace_store 内部自带 RLock 读写锁，所以多个请求同时写事件也不会乱，之前设计的锁在这里就发挥作用了。
    @router.get(
        "/capabilities",
        response_model=list[CapabilityDescriptor]
    )
    def list_capabilities()->list[CapabilityDescriptor]:
        return registry.list_descriptors()

    @router.post(
        "/capabilities/{capability_id}/run",
        response_model=CapabilityRunResponse,
    )
    def run_capability(
        capability_id:str,
        payload:CapabilityRunRequest,
        request:Request
    )->CapabilityRunResponse:
        try:
            registry.get(capability_id=capability_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=("unknown capability: "
                        f"{capability_id}")
            )

        try:
            return registry.run(
                capability_id=capability_id,
                request=payload,
                trace_store=request.app.state.trace_store,
            )
        except CapabilityExecutionError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "capability_id": (
                        exc.capability_id
                    ),
                    "run_id": exc.run_id,
                    "message": exc.message,
                },
            ) from exc

    @router.get(
        "/runs/{run_id}/trace",
        response_model=RunTraceResponse,
    )
    def get_run_trace(
        run_id: str,
        request: Request,
    ) -> RunTraceResponse:
        try:
            trace = (
                request.app.state
                .trace_store
                .get_run(run_id)
            )
        except TraceNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=(
                    "run trace not found: "
                    f"{run_id}"
                ),
            ) from exc

        return RunTraceResponse(
            run_id=trace.run_id,
            event_count=trace.event_count,
            events=[
                event.to_dict()
                for event in trace.events
            ],
            created_at=trace.created_at,
            updated_at=trace.updated_at,
        )

    return router


capability_registry = CapabilityRegistry()



# 系统启动阶段
#     ↓
# 1. 创建 TraceStore（比如 InMemoryTraceStore）
# 2. 创建各个业务能力（比如 RAG 问答、查询重写、纯检索等）
#    每个能力 = 描述符 + 业务处理函数
# 3. 把所有能力注册到 CapabilityRegistry
# 4. 用注册中心生成 FastAPI 路由，挂到应用上
# 5. 把 trace_store 存到 app.state 全局
#     ↓
# 用户调用阶段
#     ↓
# 用户调用 POST /capabilities/rag_ask/run，传问题参数
#     ↓
# 路由层收到请求，从 app.state 拿到 trace_store
#     ↓
# 调用 registry.run()
#     ↓
# 生成 run_id → 创建 TraceRecorder → 记录开始事件
#     ↓
# 执行业务处理函数（比如完整 RAG 链路）
# 业务内部可以用 recorder 记录重写、检索、生成等子事件
#     ↓
# 执行成功 → 记录完成事件
#     ↓
# 组装标准化响应返回给用户
#     ↓
# 用户拿到结果，里面有 run_id
#     ↓
# 排障阶段
#     ↓
# 用户调用 GET /runs/xxx/trace，传入 run_id
#     ↓
# 从 trace_store 拉出整条链路的所有事件
# 按时间排序，返回完整时间线
#     ↓
# 哪个阶段慢、哪个步骤错、各项指标多少，一目了然
