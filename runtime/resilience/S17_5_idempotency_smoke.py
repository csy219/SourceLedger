# 逐行代码全解析：两级幂等功能冒烟测试脚本

# 这段代码是**请求级幂等 + 工具级幂等的完整功能验证脚本**，通过真实调用数据库仓储层，
# 验证两套幂等服务的核心能力：**相同标识重复调用时，业务逻辑只执行一次，第二次直接返回历史结果（重放）**。

import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.S15_state_reference import (
    RunState,
    ToolCallRecord,
)
from runtime.db.S16_3_run_repository import (
    RunStateRepository,
)
from runtime.db.S16_4_idempotency_repository import (
    IdempotencyRepository,
)
from runtime.db.S16_4_tool_call_repository import (
    ToolCallRepository,
)
from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)
from runtime.resilience.S17_5_idempotency import (
    RequestIdempotencyService,
    ToolExecutionService,
)

def main()->int:
    # 1. 数据库与依赖初始化
    # - `engine`：数据库引擎对象，管理数据库连接
    # - `session_factory`：数据库会话工厂，用来创建每次数据库操作的会话
    # - **依赖链条起点**：所有仓储都依赖会话工厂，所有服务都依赖仓储，这是典型的分层依赖注入架构
    engine=create_db_engine()
    session_factory=create_session_factory(engine)

    # 2. 仓储与服务实例化
    run_repository=RunStateRepository(session_factory)
    request_service=RequestIdempotencyService(
        IdempotencyRepository(session_factory)
    )
    tool_service=ToolExecutionService(
        ToolCallRepository(session_factory)
    )


    # 3. 创建运行记录（测试上下文）
    # - `state`：创建一个 RunState 运行状态实例
    # - `thread_id`：线程 / 测试标识，标记这是幂等冒烟测试
    # - `goal`：运行目标描述
    # - `max_steps`：最大步骤数，测试用随便设一个值
    # - `run_repository.create(state)`：把运行记录写入数据库
    # - **核心作用**：生成唯一的 `state.run_id`，后续所有幂等操作、工具调用都要关联这个 `run_id`，用来追踪归属，符合数据库的外键关联设计
    state = RunState.create(
        thread_id="thread-idempotency-smoke",
        goal="测试请求级和工具级幂等",
        max_steps=10,
    )
    run_repository.create(state)

    # 4. 第一部分：请求级幂等功能测试
    # - `request_calls = {"count": 0}`
    # - 业务函数执行计数器，用**字典**而不用普通整数
    # - 为什么用字典？Python 闭包内部不能直接修改外部的不可变类型（int），会被识别为局部变量；用可变对象（字典）就可以修改内部的值，实现计数效果
    # - 核心作用：统计业务函数真正被执行了几次，验证幂等是否生效
    # - `request_key`
    # - 请求级幂等键，加 `request:` 前缀做命名空间
    # - 用 uuid 生成唯一值，保证每次测试用的都是全新的 key，不受历史数据影响
    # - `request_func()`
    # - 模拟的业务函数，就是幂等要保护的目标逻辑
    # - 每次执行计数器 +1，返回一个字典结果
    # - 返回结果里带 `call` 字段，可以直观看到是第几次执行的结果
    request_calls = {"count": 0}
    request_key = (
        f"request:{uuid.uuid4().hex}"
    )

    def request_func() -> dict:
        request_calls["count"] += 1
        return {
            "result": "request-ok",
            "call": request_calls["count"],
        }

    # 两次调用幂等服务
    # - **第一次调用**：key 不存在，会真正执行 `request_func`，计数器 +1，结果写入数据库，返回 `replayed=False`
    # - **第二次调用**：相同 key，记录已存在且状态为成功，直接返回历史结果，**不会执行 `request_func`**，计数器不变，返回 `replayed=True`
    # - **验证目标**：两次调用相同的幂等键，业务函数只执行 1 次，第二次是重放
    first_request = request_service.execute(
        key=request_key,
        run_id=state.run_id,
        func=request_func,
    )
    second_request = request_service.execute(
        key=request_key,
        run_id=state.run_id,
        func=request_func,
    )

    # 5. 第二部分：工具级幂等功能测试
    # - `tool_calls = {"count": 0}`：工具函数执行计数器，和上面同理，用来验证工具函数只执行一次
    # - `record`：工具调用记录对象
    # - `tool_call_id`：工具调用唯一 ID，是工具级幂等的核心键，相同 ID 视为同一次调用
    # - `tool_name`：工具名称，模拟 shell 执行工具
    # - `arguments`：工具参数，模拟执行 pytest 命令
    # - `tool_func()`：模拟的工具执行函数，每次执行计数器 +1，返回执行结果
    tool_calls = {"count": 0}
    record = ToolCallRecord(
        tool_call_id=(
            f"tool-{uuid.uuid4().hex}"
        ),
        tool_name="shell.run",
        arguments={"command": "pytest -q"},
    )

    def tool_func() -> dict:
        tool_calls["count"] += 1
        return {
            "exit_code": 0,
            "call": tool_calls["count"],
        }

    # 两次调用工具幂等服务
    # - **第一次调用**：tool_call_id 不存在，创建记录，执行 `tool_func`，计数器 +1，结果落库，返回 `replayed=False`
    # - **第二次调用**：相同 tool_call_id，记录已存在且成功，直接返回历史结果，不执行工具函数，计数器不变，返回 `replayed=True`
    # - **验证目标**：相同的工具调用重复触发，工具逻辑只执行 1 次，第二次是重放
    first_tool = tool_service.execute(
        run_id=state.run_id,
        record=record,
        func=tool_func,
    )
    second_tool = tool_service.execute(
        run_id=state.run_id,
        record=record,
        func=tool_func,
    )

    output = {
        "request_first_replayed": (
            first_request.replayed
        ),
        "request_second_replayed": (
            second_request.replayed
        ),
        "request_call_count": (
            request_calls["count"]
        ),
        "request_value": second_request.value,
        "tool_first_replayed": (
            first_tool.replayed
        ),
        "tool_second_replayed": (
            second_tool.replayed
        ),
        "tool_call_count": tool_calls["count"],
        "tool_value": second_tool.value,
    }

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())