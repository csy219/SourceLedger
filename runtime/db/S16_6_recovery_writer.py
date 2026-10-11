# 这段代码是**跨进程状态恢复验证的「写入端」测试脚本**，核心目的是：
# 构造一个完整的、包含上下文和工具调用的运行状态，通过 `DatabaseCheckpointer` 持久化到数据库，
# 再把验证所需的关键元数据写入一个 artifact 文件，供另一个独立进程（读取端）加载并校验，以此证明「进程 A 保存的状态，进程 B 可以完整、正确地恢复出来」。
# 它是验证检查点机制可靠性的核心测试用例，覆盖了「完整状态序列化 → 数据库持久化 → 跨进程还原」整条链路。
# 解析命令行参数 → 初始化数据库组件 → 创建任务主记录
#     ↓
# 手动构造完整运行状态（上下文消息+工具调用记录）
#     ↓
# 调用 Checkpointer 保存状态快照到数据库
#     ↓
# 将验证元数据写入 artifact 文件
#     ↓
# 输出关键信息，退出

import argparse
import json
import os
from pathlib import Path

from runtime.S15_state_reference import (
    RunState,
    RunStatus,
    ToolCallRecord,
)

from runtime.db.S16_3_run_repository import (
    RunStateRepository
)

from runtime.db.checkpointer import(
    DatabaseCheckpointer
)

from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)

# - 接收一个 `--artifact` 参数，指定输出的元数据文件路径。
# - **作用**：跨进程测试的「信息桥梁」。两个独立进程无法共享内存变量，因此通过文件传递 `run_id`、版本号、预期值等验证依据。
def parse_args()->argparse.Namespace:
    parser=argparse.ArgumentParser()
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
    )
    return parser.parse_args()


def main()->int:
    args=parse_args()
    engine=create_db_engine()
    session_factory=create_session_factory(engine)

    run_repository=RunStateRepository(session_factory)
    checkpointer=DatabaseCheckpointer(session_factory)

    # ① 创建基础任务
    state=RunState.create(
        thread_id="thread-cross-process-recovery",
        goal="验证跨进程恢复",
        max_steps=10,
    )

    run_repository.create(state)

    # ② 修改运行时核心状态
    state.status=RunStatus.RUNNING
    state.current_node="after_tool"
    state.step_count=2

    # ③ 构造完整对话上下文
    #     手动塞入三轮完整的对话消息：用户提问 → 助手发起工具调用 → 工具返回结果。
    # - **设计意图**：验证嵌套复杂结构的序列化完整性。如果只存简单字段，无法发现深层嵌套对象的序列化丢失、类型畸变等问题。
    state.context.messages.extend(
        [
            {
                "role": "user",
                "content": "执行测试",
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-recovery-1",
                        "type": "function",
                        "function": {
                            "name": "shell.run",
                            "arguments": (
                                '{"command":"pytest -q"}'
                            ),
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-recovery-1",
                "content": '{"exit_code":0}',
            },
        ]
    )
    # ④ 构造工具调用记录
    # 模拟一次完整的工具调用生命周期，并放入状态的工具调用字典中，验证工具调用这一层也能被完整持久化和恢复。
    record=ToolCallRecord(
        tool_call_id="call-recovery-1",
        tool_name="shell_run",
        arguments={"command":"pytest -q"}
    )
    record.mark_running()
    record.mark_succeeded({"exit_code":0})
    state.tool_calls[record.tool_call_id]=record

    # 4. 保存检查点（核心操作）
    # 调用数据库检查点器，将整个 `RunState` 对象：
    # 1. 序列化为字典（JSON）
    # 2. 开启事务、锁定任务行
    # 3. 插入新版本快照记录
    # 4. 同步更新任务主表状态
    # 5. 提交事务
    # 这一步完成后，完整的运行状态就持久化到了数据库中，和当前进程完全解耦。
    checkpoint=checkpointer.save(state,node="after_tool")


    # 5. 写入 artifact 验证文件
    # 将验证所需的全部元数据写入 JSON 文件：

    # - `run_id` + `version`：告诉读取端去数据库加载哪个版本的快照
    # - 各个 `expected_*`：读取端加载后用来逐项对比的预期值
    # - `writer_pid`：写入进程的 PID，用来证明确实是**跨进程**恢复（读取端 PID 和写入端不同）
    artifact = {
        "run_id": state.run_id,
        "version": checkpoint.version,
        "expected_status": "running",
        "expected_node": "after_tool",
        "expected_step_count": 2,
        "expected_tool_status": "succeeded",
        "writer_pid": os.getpid(),
    }

    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"writer_pid={artifact['writer_pid']}")
    print(f"run_id={state.run_id}")
    print(f"checkpoint_version={checkpoint.version}")
    print(f"artifact={args.artifact}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ## 三、核心设计意图与测试逻辑

# ### 1. 为什么要做跨进程恢复测试？

# 检查点机制的核心价值就是**进程无关的状态持久化**：任务不会因为进程崩溃、服务重启、机器切换而丢失。

# - 如果只在同一个进程里存了又读，只能验证序列化本身正确，无法验证「真正脱离内存后再还原」的可靠性。
# - 两个完全独立的 Python 进程，通过数据库 + artifact 文件协作，才能真实模拟「进程退出 → 新进程恢复」的生产场景。

# ### 2. 为什么手动构造完整状态？

# 这是测试的「控制变量法」：

# - 不启动真实工作流引擎，避免工作流本身的逻辑干扰测试结果
# - 精确控制每一个字段的值，读取端可以逐项精确对比
# - 覆盖嵌套结构、复杂对象、枚举、时间等各种边界类型

# ### 3. 对应的读取端逻辑（验证侧）

# 这个脚本只负责「写」，一般会配套一个读取端脚本，逻辑大致是：

# 1. 读取 artifact 文件，拿到 `run_id`、`version` 和所有预期值
# 2. 初始化自己的数据库组件和 checkpointer
# 3. 调用 `checkpointer.load_version(run_id, version)` 从数据库加载状态
# 4. 逐项校验：状态、节点、步数、工具状态、上下文消息数量、工具调用结果
# 5. 校验 `os.getpid() != writer_pid`，证明确实跨进程
# 6. 全部匹配则测试通过，否则失败

# ---

# ## 四、和整套体系的关联

# - 底层复用 `RunStateRepository`、`DatabaseCheckpointer`、`state_codec` 全套组件
# - 验证了之前所有模块组合起来的端到端能力
# - 是 CI/CD 流水线里的集成测试用例，每次代码变更都会自动跑，防止检查点机制被改坏