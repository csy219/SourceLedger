# 这是 **RAG 系统的文档上传 API 接口模块**，基于 FastAPI 路由化实现，完整覆盖「文件接收 → 安全校验 → 本地存储 → 向量化索引 → 标准化响应」全流程。核心能力包括：

# 1. 仅支持 PDF 格式文件上传，做文件名安全校验，防范路径遍历攻击
# 2. 自动创建上传目录，流式写入文件，高效处理文件存储
# 3. 调用 PDF 索引引擎完成文档解析、切分、向量化入库
# 4. 统一异常处理与标准化响应结构，符合 RESTful 规范


# `import shutil`：Python 内置高级文件操作模块，这里使用其 `copyfileobj` 方法实现文件流的高效复制，用于将上传的文件流写入本地磁盘。
import shutil

from pathlib import Path

# - `APIRouter`：FastAPI 的路由类，用于模块化注册接口，将文档相关接口分组管理，无需全部挂载在主应用上，提升代码可维护性。
# - `File`：FastAPI 的文件参数声明工具，作为参数装饰器，用于标识接口接收文件上传参数。
# - `HTTPException`：FastAPI 的 HTTP 异常类，用于抛出指定状态码和错误详情的 HTTP 错误，统一异常响应格式。
# - `UploadFile`：FastAPI 的上传文件封装类，代表客户端上传的文件对象，包含文件名、文件流等属性。
# - `status`：FastAPI 内置的 HTTP 状态码常量集合，避免硬编码数字，提升代码可读性。
from fastapi import (
    APIRouter,
    File,
    HTTPException,
    UploadFile,
    status,
)


from runtime.api.S19_1_schemas import (
    UploadResponse,
)


# 2. 路由实例初始化
# **变量 `router`**：文档模块的路由实例，所有该模块下的接口都注册在这个路由上。
# - `prefix="/documents"`：路由前缀，该路由下所有接口的路径都会自动加上 `/documents` 前缀，最终上传接口路径为 `/documents/upload`；
# - `tags=["documents"]`：OpenAPI 文档标签，接口文档中会将该组接口归类到 `documents` 分组下，提升接口文档可读性。
router=APIRouter(
    prefix="/documents",
    tags=["documents"]
)

# 3. 文档上传接口
# - `@router.post(...)`：路由装饰器，注册一个 POST 方法的接口，路径为 `/upload`（拼接前缀后为 `/documents/upload`）。
#   - `response_model=UploadResponse`：指定响应数据模型，FastAPI 会自动对返回值做类型校验和 JSON 序列化，同时生成接口文档；
#   - `status_code=status.HTTP_200_OK`：指定接口成功时的默认 HTTP 状态码为 200。
# - `async def upload_document`：异步上传处理函数，是接口的核心处理逻辑。
# - `file: UploadFile = File(...)`：文件上传参数，由 FastAPI 自动注入客户端上传的文件；
#   - `File(...)` 中的 `...` 表示该参数为必填项，客户端必须上传文件，否则返回参数错误。
@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_document(
    file:UploadFile=File(...),
)->UploadResponse:
    from pdf_rag import (
        UPLOAD_DIR,
        index_pdf,
    )
    # class UploadFile:
    # filename: str | None        # 原始文件名，前端传上来的
    # content_type: str | None   # mime类型，如 application/pdf
    # file: spooledtemporaryfile.SpooledTemporaryFile  # 底层文件对象
    # size: int | None
    original_name=file.filename or ""

    # `Path(...).name` 的逻辑：
    # 1. 传入字符串（`file.filename`，比如前端传的 `D:/user/xxx/报告.pdf`）
    # 2. `Path` 把它解析成路径对象
    # 3. `.name` 属性：取出**路径最后一段的文件名（带后缀）**
    #    - `Path("D:/user/xxx/报告.pdf").name` → `"报告.pdf"`
    #    - `Path("/etc/secret/test.txt").name` → `"test.txt"`
    #    - `Path("readme.md").name` → `"readme.md"`
    safe_name=Path(original_name).name

    # 非空校验：安全文件名为空时，抛出 400 客户端错误，提示文件名不能为空。
    if not safe_name:
        raise HTTPException(
            status_code=400,
            detail="文件名不能空"
        )
    # - 格式校验：将文件名转小写后判断后缀是否为 `.pdf`，不区分大小写（适配 `.PDF` 大写后缀）；
    # - 非 PDF 文件直接抛出 400 错误，限制仅允许上传 PDF 文档，符合业务定位，同时避免非法文件类型上传风险。   
    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="只支持 PDF 文件",
        )
    # 3.2 文件存储
    # 确保上传存储目录存在：
    # - `parents=True`：递归创建多级父目录，即使上层目录不存在也会一并创建；
    # - `exist_ok=True`：目录已存在时不报错，避免重复创建目录抛出异常
    UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
    target_path=UPLOAD_DIR / safe_name

    # 流式写入文件：
    # - `target_path.open("wb")`：以二进制写入模式打开目标文件，`with` 语法保证文件使用完自动关闭，避免资源泄漏；
    # - **变量 `output`**：目标文件的写入流对象；
    # - `file.file`：`UploadFile` 内部的类文件对象，是上传文件的原始字节流；
    # - `shutil.copyfileobj`：高效复制文件流，直接在字节流层面拷贝，适合处理大文件，比读取全部内容再写入更省内存。
    with target_path.open("wb") as output:
        shutil.copyfileobj(
            file.file,
            output
        )

    # 3.3 文档索引与异常处理
    # - 捕获索引过程中的所有异常，转换为 HTTP 500 服务端错误；
    # - 错误详情仅返回异常类型名称，不暴露完整堆栈与内部信息，兼顾排查性与安全性；
    # - `from exc`：Python 异常链语法，保留原始异常的堆栈信息，服务端日志可以看到完整报错，方便问题定位。
    try:
        indexed_chunks=index_pdf(target_path)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=("文档索引失败: "
            f"{type(exc).__name__}"),
        )from exc

    # 返回标准化的上传响应对象：
    # - `filename`：处理后的安全文件名；
    # - `source`：文件来源标识，这里用文件名填充；
    # - `indexed_chunks`：成功索引的文本块数量；
    # - `status`：处理状态，标记为 `indexed`（已完成索引）。
    return UploadResponse(
        filename=safe_name,
        source=safe_name,
        indexed_chunks=indexed_chunks,
        status="indexed"
    )

### 三、核心设计总结

# 1. **安全防护完备**：通过纯文件名提取防范路径遍历攻击，限制文件格式为 PDF，从入口层降低安全风险。
# 2. **流式处理高效**：使用文件流拷贝写入文件，内存占用低，支持大文件上传。
# 3. **模块化路由设计**：通过 `APIRouter` 实现接口分组，与主应用解耦，便于扩展和维护。
# 4. **标准化交互**：统一响应模型、统一异常格式，符合 RESTful 规范，天然支持自动生成接口文档。
# 5. **异常友好**：对外仅暴露异常类型，对内保留完整堆栈，兼顾安全与可运维性。