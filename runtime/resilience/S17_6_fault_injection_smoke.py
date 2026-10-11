import json

# 读取和复制环境变量，控制子进程运行环境
import os

# 启动独立子进程运行每个测试脚本，保证环境隔离
import subprocess

# 获取当前 Python 解释器路径，保证子进程用相同环境
import sys
import time
from pathlib import Path
from typing import Any


# 二、SCENARIOS：测试场景配置
# 定义 4 个待测的弹性能力场景，每个场景包含**名称、被测模块、校验关键字**，是测试执行的配置清单。
# 字段	作用
# name	场景名称，用于报告和日志展示，清晰标识测试项
# module	被测 Python 模块路径，对应每个组件的冒烟测试脚本，用 -m 方式运行
# required_text	预期输出中必须包含的关键字列表；只要输出里全包含这些关键字，就认为功能基本正常
SCENARIOS = [
    {
        "name": "timeout_retry_backoff",
        "module": (
            "runtime.resilience."
            "S17_2_executor_smoke"
        ),
        "required_text": [
            "success_attempts",
            "OperationTimeout",
            "RetryExhausted",
            "NonRetryableOperationError",
        ],
    },
    {
        "name": "fallback_circuit_breaker",
        "module": (
            "runtime.resilience."
            "S17_3_fallback_breaker_smoke"
        ),
        "required_text": [
            "bm25_only",
            "FallbackExhausted",
            "CircuitOpenError",
            "closed",
        ],
    },
    {
        "name": "rate_limit_distributed_lock",
        "module": (
            "runtime.resilience."
            "S17_4_rate_limit_lock_smoke"
        ),
        "required_text": [
            "local_rate_limit",
            "redis_rate_limit",
            "first_lock_acquired",
            "second_lock_acquired_while_held",
        ],
    },
    {
        "name": "request_tool_idempotency",
        "module": (
            "runtime.resilience."
            "S17_5_idempotency_smoke"
        ),
        "required_text": [
            "request_call_count",
            "tool_call_count",
            "request-ok",
            "exit_code",
        ],
    },
]

# 三、run_scenario：单场景执行函数
def run_scenario(
    scenario: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()

    # - `env`：子进程的环境变量，先复制当前环境，再追加自定义配置
    # - `PYTHONIOENCODING=utf-8`：强制 Python 标准输出 / 错误的编码为 UTF-8，避免 Windows 下中文乱码
    # - `PYTHONDONTWRITEBYTECODE=1`：禁止生成 `.pyc` 字节码缓存文件，保持项目目录干净
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"


    # - `sys.executable`：当前 Python 解释器的完整路径，保证子进程和主进程用同一个 Python 环境，避免版本不一致
    # - `-m`：以模块方式运行脚本，和命令行 `python -m xxx` 效果一致，保证包导入路径正确
    # - `cwd=project_root`：子进程工作目录设为项目根目录，所有相对导入都基于这个路径
    # - `text=True`：输出以字符串形式返回，不用手动解码字节
    # - `capture_output=True`：同时捕获标准输出（stdout）和标准错误（stderr），不会直接打印到控制台
    # - `completed`：子进程执行结果对象，包含退出码、输出内容等
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            scenario["module"],
        ],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
    )

    elapsed_ms = (
        time.perf_counter() - started
    ) * 1000

    # 合并输出内容
    # - `output`：合并标准输出和标准错误
    # - 为什么合并？有些警告、错误信息可能输出到 stderr，合并后统一校验，避免漏检
    output = (
        completed.stdout
        + completed.stderr
    )

    # - `missing_tokens`：缺失的关键字列表
    # - 逻辑：遍历所有预期关键字，找出不在输出中的内容；列表为空说明所有关键字都命中了
    missing_tokens = [
        token
        for token in scenario["required_text"]
        if token not in output
    ]


    # **判断是否通过**
    # - `passed`：是否通过测试，两个条件必须同时满足：
    # 1. 子进程退出码为 0：程序正常执行结束，没有崩溃
    # 2. 没有缺失的关键字：输出包含所有预期核心字段，功能基本正常
    passed = (
        completed.returncode == 0
        and not missing_tokens
    )

    return {
        "name": scenario["name"],
        "module": scenario["module"],
        "return_code": completed.returncode,
        "elapsed_ms": round(elapsed_ms, 2),
        "missing_tokens": missing_tokens,
        "passed": passed,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    project_root = (
        Path(__file__).resolve().parents[2]
    )
    report_path = (
        project_root
        / "evaluation"
        / "reports"
        / "S17_6_fault_injection.json"
    )

    results = [
        run_scenario(
            scenario,
            project_root,
        )
        for scenario in SCENARIOS
    ]

    summary = {
        "scenarios": len(results),
        "passed": sum(
            1
            for item in results
            if item["passed"]
        ),
        "failed": sum(
            1
            for item in results
            if not item["passed"]
        ),
        "all_passed": all(
            item["passed"]
            for item in results
        ),
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

    print("===== S17 Fault Injection =====")
    for item in results:
        print(
            f"{item['name']} "
            f"passed={item['passed']} "
            f"return_code={item['return_code']} "
            f"elapsed_ms={item['elapsed_ms']}"
        )
        if item["missing_tokens"]:
            print(
                "missing_tokens="
                f"{item['missing_tokens']}"
            )

    print(
        f"all_passed={summary['all_passed']}"
    )
    print(
        f"report={report_path.resolve()}"
    )

    if not summary["all_passed"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())