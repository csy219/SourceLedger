# 这是一套基于 Pydantic 构建的 **API 接口数据契约模型集**，覆盖服务健康检查、会话管理、文档上传、问答交互、任务状态查询、通用错误返回等全业务场景。核心价值是：

# 1. 自动完成请求 / 响应数据的类型校验、长度校验、默认值填充，从接口层拦截非法参数；
# 2. 统一前后端、服务间的数据结构，降低联调成本；
# 3. 天然支持 FastAPI 等 Web 框架自动生成 OpenAPI 文档、自动序列化 / 反序列化。


# - `from enum import Enum`：导入 Python 标准库的枚举基类，用于定义固定取值的状态字段，确保状态值只能是预定义选项，避免非法字符串传入。
# - `BaseModel`：Pydantic 核心基类，所有数据模型继承它后，会自动获得类型强制转换、数据校验、JSON 序列化、字段默认值处理等能力。
# - `Field`：Pydantic 字段配置工具，用于给字段添加额外校验规则（长度范围、最值）、默认值、描述信息等，实现更精细化的参数控制。
from enum import Enum
from pydantic import (
    BaseModel,
    Field
)


# 2. TaskStatus 任务状态枚举
class TaskStatus(str,Enum):
    PENDING="pending"
    RUNNING="running"
    WAITING_APPROVAL="waiting_approval"
    COMPLETED="completed"
    FAILED="failed"
    CANCELLED="cancelled"


# 3.1 HealthResponse 健康检查响应
class HealthResponse(BaseModel):
    status:str
    service:str
    version:str


# 3.2 ReadinessResponse 就绪检查响应
# - 作用：服务就绪性检查接口的返回结构，比健康检查更细粒度，判断服务是否可以接收业务流量，常用于 K8s 等容器编排的就绪探针。
# - 字段说明：
#   - `ready: bool`：整体就绪标记，`True` 代表服务所有依赖都正常，可以接入请求；`False` 代表不可用。
#   - `database: bool`：数据库组件是否就绪。
#   - `redis: bool`：Redis 缓存组件是否就绪。
#   - `details: dict[str, str]`：额外的就绪详情字典，可以存放各个组件的详细状态、错误信息等；
#     - `default_factory=dict`：默认值为空字典。使用工厂函数而不是直接写 `{}`，是为了避免所有实例共享同一个字典对象（Python 可变默认值陷阱），保证每个实例的字典相互独立。
class ReadinessResponse(BaseModel):
    ready:bool
    database:bool
    redis:bool
    details:dict[str,str]=Field(default_factory=dict)


# 4. 文档上传模型
# UploadResponse 上传响应
# - 作用：文档上传并完成索引处理后的返回结构，告知客户端上传结果。
# - 字段说明：
#   - `filename: str`：上传的文件名称。
#   - `source: str`：文件来源标识，比如 `local`（本地上传）、`oss`（对象存储导入）、`third_party`（第三方同步）等。
#   - `indexed_chunks: int`：文件被切分并成功向量化索引的文本块数量，用于确认处理进度。
#   - `status: str`：上传处理状态，比如 `success` / `failed`。
class UploadResponse(BaseModel):
    filename:str
    source:str
    indexed_chunks:int
    status:str


# 5. 会话管理类模型
# 5.1 CreateSessionRequest 创建会话请求
# - 作用：创建对话会话的请求参数结构，客户端发起创建会话时传入。
# - 字段说明：
#   - `user_id: str`：用户唯一标识，用于关联用户与会话。
#     - `min_length=1`：非空校验，禁止空字符串的用户 ID。
#     - `max_length=128`：长度上限，防止非法超长参数，同时适配数据库字段长度。
#   - `title: str`：会话标题，用于展示会话列表。
#     - `default=""`：默认值为空字符串，用户不传时自动留空。
#     - `max_length=255`：标题长度上限，适配常规数据库字符串字段长度。
class CreateSessionRequest(BaseModel):
    user_id:str=Field(
        min_length=1,
        max_length=128,
    )
    title:str=Field(
        default="",
        max_length=255,
    )


# 5.2 CreateSessionResponse 创建会话响应
# - 作用：创建会话成功后的返回结构，返回会话的核心标识。
# - 字段说明：
#   - `session_id: str`：会话唯一 ID，标识一整段对话周期。
#   - `thread_id: str`：对话线程 ID，一个会话下可以包含多个线程，用于分流不同话题的对话。
#   - `user_id: str`：对应用户 ID，回显给客户端确认。
#   - `status: str`：会话状态，通常为 `active`。
class CreateSessionResponse(BaseModel):
    session_id:str
    thread_id:str
    user_id:str
    status:str


# 6. 问答交互类模型
# 6.1 AskRequest 提问请求
# - 作用：用户向模型发起提问的请求参数结构，是核心业务接口的入参。
# - 字段说明：
#   - `question: str`：用户的提问文本。
#     - `min_length=1`：不能为空问题。
#     - `max_length=4000`：问题长度上限，控制输入长度，避免超出模型上下文窗口。
#   - `thread_id: str`：对话线程 ID，用于关联历史上下文。
#     - `default="default"`：客户端不传时，默认使用 `default` 线程，适配单线程简单对话场景。
#     - 长度校验 1~128 位。
#   - `request_id: str | None`：客户端请求 ID，用于幂等校验、全链路追踪、日志排查。
#     - `default=None`：可选参数，不传则为空。
#     - `max_length=128`：长度限制。
#   - `stream: bool = False`：是否开启流式响应；`False` 为一次性返回完整结果，`True` 为逐字流式输出。默认关闭流式。
class AskRequest(BaseModel):
    question:str=Field(
        min_length=1,
        max_length=4000,
    )
    thread_id:str=Field(
        default="default",
        min_length=1,
        max_length=128,
    )
    request_id:str | None=Field(
        default=None,
        max_length=128,
    )
    stream:bool=False


# 6.2 CitationItem 引用项模型
# - 作用：回答中引用的参考文献条目结构，对应检索到的文档片段，用于回答的溯源。
# - 字段说明：
#   - `citation_id: str`：引用编号，比如 `C1`、`C2`，和回答正文中的 `[C1]` 标记一一对应。
#   - `source: str`：引用来源名称，比如文档文件名、网页 URL、书籍名称。
#   - `page: int`：引用内容在来源文档中的页码。
class CitationItem(BaseModel):
    citation_id:str
    source:str
    page:int


# 6.3 AskResponse 提问响应
# - 作用：问答接口的返回结构，包含回答内容、引用来源、状态与性能指标，是核心业务接口的出参。
# - 字段说明：
#   - `run_id: str`：本次提问的执行 ID，用于单次请求的全链路追踪。
#   - `thread_id: str`：对应的对话线程 ID。
#   - `status: TaskStatus`：任务当前状态，使用前面定义的 `TaskStatus` 枚举，保证状态取值规范。
#   - `answer: str`：模型生成的回答文本。
#   - `citations: list[CitationItem]`：回答涉及的所有引用文献列表。
#     - `default_factory=list`：默认值为空列表，使用工厂函数避免可变默认值问题。
#   - `context_tokens_est: int`：本次请求消耗的上下文 Token 估算值，用于计费、限流统计；默认值为 0。
#   - `latency_ms: float`：请求处理耗时，单位毫秒，用于性能监控；默认值为 0.0。
#   - `replayed: bool`：是否为缓存重放结果；`True` 代表命中缓存直接返回，未实际执行推理；默认值为 `False`。
class AskResponse(BaseModel):
    run_id:str
    thread_id:str
    status:TaskStatus
    answer:str
    citations:list[CitationItem]=Field(
        default_factory=list
    )
    context_tokens_est:int=0
    input_tokens:int=0
    output_tokens:int=0
    total_tokens:int=0
    cache_read_tokens:int=0
    latency_ms:float=0.0
    replayed:bool=False


# 7. 任务状态查询模型
# TaskStatusResponse 任务状态响应
# - 作用：异步任务状态查询接口的返回结构，用于长耗时任务的进度追踪。
# - 字段说明：
#   - `run_id: str`：任务执行 ID，对应提问的 run_id。
#   - `thread_id: str`：对应的线程 ID。
#   - `status: TaskStatus`：任务当前状态，枚举类型。
#   - `current_node: str`：当前执行的工作流节点名称，用于定位任务执行到哪一步。
#   - `step_count: int`：已执行的步骤数。
#   - `max_steps: int`：总步骤数，可以和已执行步数配合计算进度百分比。
#   - `error: str = ""`：错误信息，任务失败时存放错误描述；默认为空字符串。
class TaskStatusResponse(BaseModel):
    run_id:str
    thread_id:str
    status:TaskStatus
    current_node:str
    step_count:int
    max_steps:int
    error:str=""

# 8. 通用错误模型
# ErrorResponse 错误响应
# - 作用：所有接口异常场景的统一返回结构，实现全系统错误信息的标准化。
# - 字段说明：
#   - `error_code: str`：错误码，比如 `PARAM_INVALID`、`SESSION_NOT_FOUND`、`INTERNAL_ERROR`，用于程序判断错误类型、做分支处理。
#   - `message: str`：人类可读的错误描述信息，用于展示给用户或开发排查。
#   - `request_id: str | None = None`：对应请求 ID，用于链路排查；可选，默认为空。
class ErrorResponse(BaseModel):
    error_code:str
    message:str
    request_id:str | None =None



### 三、核心设计总结

# 1. **全场景覆盖**：覆盖健康检查、会话管理、文档上传、问答交互、任务追踪、错误返回六大类接口，形成完整的 API 数据契约。
# 2. **严格校验**：通过 Pydantic 的类型系统 + Field 约束，实现从数据类型到长度范围的多层校验，在接口入口层拦截非法参数。
# 3. **状态统一**：核心任务状态使用枚举统一管理，避免散点字符串导致的状态不一致、拼写错误等问题。
# 4. **工程友好**：合理的默认值设计、可选字段设计，兼顾兼容性与扩展性；标准结构天然支持自动生成 OpenAPI 接口文档，降低联调成本。
