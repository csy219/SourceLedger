### 一、代码整体功能概述
# 这是一个针对 FastAPI 接口的**并发压力测试脚本**，完整实现了
# 「参数配置→自动启动服务→健康检查→异步并发压测→指标统计→报告生成→进程清理」的全流程压测能力，
# 核心统计延迟分位值、成功率、Token 消耗与预估成本，是典型的接口性能基准测试工具。

# `argparse`Python 标准库，解析命令行参数，支持自定义压测请求数、并发数、端口
import argparse

# `asyncio`异步 IO 标准库，实现高并发异步请求调度，是压测并发能力的核心
import asyncio
import json
import os

# `statistics`数学统计库，计算延迟平均值等统计指标
import statistics

# `subprocess`子进程管理，启动 uvicorn 运行 FastAPI 目标服务
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# `httpx`支持同步 / 异步的 HTTP 客户端，原生支持异步，用于发送压测请求
import httpx

# 2. 参数解析函数 `parse_args`
# - 功能：定义并解析命令行参数，返回配置好的参数对象。
# - 核心变量：
#   - `parser`：参数解析器实例，负责参数定义与解析逻辑。
#   - `--requests`：总压测请求数，整数，默认 20。
#   - `--concurrency`：最大并发请求数，整数，默认 5。
#   - `--port`：目标 FastAPI 服务监听端口，整数，默认 8010。
#   - 返回值：`argparse.Namespace` 对象，可通过属性访问各参数值。
def parse_args()->argparse.Namespace:
    parser=argparse.ArgumentParser(
        description="S19-6 FastAPI 并发压测"
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8010,
    )
    return parser.parse_args()

# 3. 百分位计算函数 `percentile`
# - 功能：计算一组数值的指定百分位（如 P50、P95），是压测延迟统计的核心指标。
# - 核心变量：
#   - `values`：输入数值列表，此处为成功请求的延迟数据（单位 ms）。
#   - `ratio`：百分位比例，0.5 对应 P50（中位数），0.95 对应 P95。
#   - `ordered`：从小到大排序后的数值列表，百分位计算依赖有序数据。
#   - `index`：百分位对应有序列表的索引，通过 `(长度-1) × 比例` 取整得到，是简化的近邻百分位算法。
#   - 返回值：对应百分位的数值，保留 2 位小数；空列表返回 0.0。
def percentile(
    values:list[float],
    ratio:float,
)->float:
    if not values:
        return 0.0
    ordered=sorted(values)
    index=int(
        (len(values)-1)*ratio
    )
    return round(ordered[index],2)

# 4. 服务等待函数 `wait_for_server`
# - 功能：轮询健康检查接口，等待目标服务启动就绪，超时则抛出异常终止压测。
# - 核心变量：
#   - `base_url`：目标服务基础地址，格式为 `http://127.0.0.1:端口`。
#   - `timeout_seconds`：最长等待超时时间，默认 30 秒。
#   - `deadline`：超时截止时间点，由单调时间 + 超时秒数计算，避免系统时间调整影响判断。
#   - `response`：健康检查接口的 HTTP 响应对象。
# - 逻辑：每 0.25 秒发起一次 GET `/health` 请求，返回 200 则认为服务就绪；超过截止时间仍未就绪则抛出运行时异常。
def wait_for_server(
    base_url:str,
    timeout_seconds:float=60.0,
)->None:
    deadline=time.monotonic()+timeout_seconds

    while time.monotonic() < deadline:
        try:
            response=httpx.get(
                f"{base_url}/health",
                timeout=2.0,
            )
            if response.status_code==200:
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError(
        "压测服务没有按时启动"
    )

# 5. 异步压测核心函数 `run_requests`
async def run_requests(
    base_url:str,
    total_requests:int,
    concurrency:int,
)->list[dict[str,Any]]:
    # 1. 并发控制器：信号量 Semaphore
    # - **`asyncio.Semaphore(N)`**：异步信号量，是**并发限流工具**。
    # - 核心作用：控制同时运行的请求数量，防止一下子把几万个请求全发出去打崩服务，也模拟真实的并发用户数。
    # - 工作逻辑：
    # - 相当于有 N 个通行证，每个请求进来先拿通行证，拿到了才能执行；
    # - 通行证发完了，后面的请求就在门口排队等；
    # - 一个请求执行完，归还通行证，排队的下一个才能拿到通行证进去。
    # - 比如 `concurrency=100`，就保证最多同时只有 100 个请求在执行。
    semaphore=asyncio.Semaphore(concurrency)

    # 2. 异步 HTTP 客户端
    # - **`httpx.AsyncClient`**：异步版的 HTTP 客户端，对应你熟悉的 `requests` 库，但它支持异步 IO，是 Python 异步压测的标准工具。
    # - **`async with`**：异步上下文管理器。
    # - 进入时：异步创建客户端、初始化连接池；
    # - 退出时：异步关闭连接、释放资源；
    # - 全程自动管理，不会泄漏连接。
    # - `timeout=60.0`：单个请求超时时间 60 秒，避免请求卡死。
    async with httpx.AsyncClient(
        timeout=60.0,
    ) as client:
        # 3. 单个请求的执行逻辑：one_request
        async def one_request(
            index:int,
        )->dict[str,Any]:
            # 3.1 信号量限流
            # - 异步获取信号量通行证。
            # - 如果当前并发数没到上限，直接拿到通行证，继续执行；
            # - 如果并发满了，就在这里挂起等待，直到有请求完成归还通行证。
            # - `async with` 保证请求结束后自动归还通行证，不用手动释放。
            async with semaphore:
                started=time.perf_counter()
                # - `request_id`：每个请求生成唯一的幂等 ID，模拟真实客户端的幂等请求。
                # - `thread_id`：线程 ID，用 `index % 5` 计算，也就是总共复用 5 个线程 ID，模拟多个对话线程，让压测更接近真实场景（不会每个请求一个新线程）。
                request_id=uuid.uuid4().hex
                thread_id=f"thread-load-{index % 5}"

                # 3.4 发起异步请求
                # - **`await client.post(...)`**：异步发送 POST 请求。
                # - 关键是 `await`：发送请求后，函数在这里**挂起**，事件循环去调度其他请求，不会傻等网络返回；
                # - 等响应回来，函数才从这里继续往下执行。
                # - 请求体：固定问题、线程 ID、请求 ID、非流式模式，和真实接口参数完全一致。
                try:
                    response = await client.post(
                        f"{base_url}/ask",
                        json={
                            "question": (
                                "RAG 的完整流程"
                                "有哪几步？"
                            ),
                            "thread_id": thread_id,
                            "request_id": request_id,
                            "stream": False,
                        },
                    )

                    elapsed_ms = (
                        time.perf_counter() - started
                    ) * 1000


                    # - 判断响应头是不是 JSON 格式，是就解析成字典，不是就返回空字典。
                    # - 容错处理：避免接口返回非 JSON 的时候解析报错。
                    payload = (
                        response.json()
                        if response.headers.get(
                            "content-type",
                            "",
                        ).startswith(
                            "application/json"
                        )
                        else {}
                    )

                    # 3.7 正常返回结果
                    return {
                        "index": index,
                        "status_code": (
                            response.status_code
                        ),
                        "latency_ms": round(
                            elapsed_ms,
                            2,
                        ),
                        "context_tokens_est": int(
                            payload.get(
                                "context_tokens_est",
                                0,
                            )
                        ),
                        "answer": payload.get(
                            "answer",
                            "",
                        ),
                        "error": "",
                    }
                # 3.8 异常捕获
                # - 捕获所有异常（网络错误、超时、连接拒绝等），保证单个请求失败不会导致整个压测崩掉。
                # - 同样记录耗时，状态码记为 0，错误信息记录异常类型和详情。
                # - 核心设计：**错误隔离**，一个请求挂了不影响其他所有请求，所有结果都能被收集统计。
                except Exception as exc:
                    elapsed_ms=(
                        time.perf_counter()-started
                    )*1000
                    return {
                        "index":index,
                        "status_code":0,
                        "latency_ms":round(elapsed_ms,2),
                        "context_tokens_est":0,
                        "answer":"",
                        "error":(
                            f"{type(exc).__name__}:"
                            f"{exc}"
                        ),
                    }
        # 4. 批量并发执行所有请求
        # 这是整个函数最核心的并发调度代码，拆解一下：

        # 1. `[one_request(index) for index in range(total_requests)]`：生成总请求数个协程对象的列表，注意：**这时候一个都还没执行**，只是创建了协程对象。
        # 2. `*[...]`：把列表解包成一个个参数，传给 `asyncio.gather`。
        # 3. **`await asyncio.gather(...)`**：
        # - 把所有协程交给事件循环，**并发启动**所有请求；
        # - 信号量会自动控制同时在途的数量；
        # - 一直等待，直到所有请求全部执行完成；
        # - 按顺序返回所有结果的列表，和传入的协程顺序一一对应。
        return await asyncio.gather(
            *[
                one_request(index)
                for index in range(total_requests)
            ]
        )
    ### 三、这么写的核心设计目的

    # 1. **精准控并发**：通过信号量严格控制最大并发数，可以模拟 10 并发、50 并发、200 并发等不同压力等级，测出服务在不同负载下的表现。
    # 2. **高吞吐低开销**：异步 IO 单线程就能支持上千并发，压测工具本身不会成为性能瓶颈，能把服务打满。
    # 3. **全数据采集**：每个请求独立计时、独立容错，成功失败都有完整记录，后续可以算出所有压测指标。
    # 4. **错误隔离**：单个请求超时、报错不影响整体压测，不会因为一个错误终止整个测试。
    # 5. **贴近真实场景**：复用线程 ID、带幂等请求 ID、标准接口参数，压测流量和真实用户请求行为一致。
    
def main()->int:
    args = parse_args()
    project_root = (
        Path(__file__).resolve().parents[2]
    )
    report_path = (
        project_root
        / "evaluation"
        / "reports"
        / "S19_6_load_test.json"
    )
    base_url = (
        f"http://127.0.0.1:{args.port}"
    )

    server=subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "runtime.api.S19_6_load_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--log-level",
            "warning",
        ],
        cwd=project_root,
        env={
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(base_url)
        results=asyncio.run(
            run_requests(
                base_url=base_url,
                total_requests=args.requests,
                concurrency=args.concurrency,
            )
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    # 6.2 结果统计与成本计算
    # - `successful`：成功请求列表（状态码 200）。
    # - `failed`：失败请求列表（状态码非 200）。
    # - `latencies`：所有成功请求的延迟列表，用于统计计算。
    # - `context_tokens`：所有成功请求的上下文 Token 列表。
    # - `input_price`：从环境变量读取的输入 Token 单价（美元 / 百万 Token），默认 0。
    # - `output_price`：输出 Token 单价，代码中定义但未实际使用。
    # - `total_context_tokens`：成功请求的上下文 Token 总和。
    # - `estimated_cost`：预估输入 Token 成本，总 Token 数 × 单价 ÷ 1000000。
    successful=[
        item
        for item in results
        if item["status_code"]==200
    ]
    failed=[
        item
        for item in results
        if item["status_code"]!=200
    ]
    latencies=[
        float(item["latency_ms"])
        for item in successful
    ]
    context_tokens=[
        int(item["context_tokens_est"])
        for item in successful
    ]
    input_price = float(
        os.getenv(
            "MODEL_INPUT_PRICE_PER_1M",
            "0",
        )
    )
    output_price = float(
        os.getenv(
            "MODEL_OUTPUT_PRICE_PER_1M",
            "0",
        )
    )
    total_context_tokens = sum(
        context_tokens
    )
    estimated_cost = (
        total_context_tokens
        * input_price
        / 1_000_000.0
    )

    # 6.3 报告生成与输出
    # - `summary`：压测汇总字典，包含核心指标：总请求数、并发数、成功 / 失败数、平均延迟、P50/P95 / 最大延迟、Token 总量 / 均值、预估成本、是否全部通过。
    # - `report`：完整报告，包含汇总统计 + 所有单次请求明细。
    # - 逻辑：
    # 1. 自动创建报告目录（多级创建、已存在不报错）。
    # 2. 写入格式化 JSON 报告，保留中文、缩进 2 空格。
    # 3. 控制台打印汇总指标与报告文件绝对路径。
    # 4. 返回退出码：有失败返回 1，全成功返回 0，符合命令行工具规范。
    summary = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "successful": len(successful),
        "failed": len(failed),
        "latency_ms_avg": round(
            statistics.mean(latencies),
            2,
        )
        if latencies
        else 0.0,
        "latency_ms_p50": percentile(
            latencies,
            0.5,
        ),
        "latency_ms_p95": percentile(
            latencies,
            0.95,
        ),
        "latency_ms_max": (
            round(max(latencies), 2)
            if latencies
            else 0.0
        ),
        "context_tokens_total": (
            total_context_tokens
        ),
        "context_tokens_avg": round(
            statistics.mean(context_tokens),
            2,
        )
        if context_tokens
        else 0.0,
        "estimated_input_cost_usd": round(
            estimated_cost,
            6,
        ),
        "all_passed": not failed,
    }
    report = {
        "summary": summary,
        "results": results,
    }
    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("===== S19-6 Load Test =====")
    for key, value in summary.items():
        print(f"{key}={value}")
    print(f"report={report_path.resolve()}")
    if failed:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

    