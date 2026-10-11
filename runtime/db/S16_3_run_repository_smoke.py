# 这段代码是一个**数据库仓储层（Repository）的冒烟测试脚本**，
# 核心目的是快速验证「数据库连接 → 会话工厂 → 仓储增 / 改 / 查」整条核心链路是否能正常跑通。
import sys
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

# 三层依赖，和之前讲的架构完全对应：
# - 业务层：状态定义 `RunState` / 枚举 `RunStatus`
# - 数据库底层：引擎创建、会话工厂创建
# - 仓储层：`RunStateRepository` 封装所有数据库操作

from runtime.S15_state_reference import (
    RunState,
    RunStatus,
)

from runtime.db.engine import (
    create_db_engine,
    create_session_factory,
)

from runtime.db.S16_3_run_repository import (
    RunStateRepository
)


def main()->int:
    # 1. 初始化数据库底层：引擎 → 会话工厂 → 仓储
    engine=create_db_engine()
    session_factory=create_session_factory(engine)
    repository=RunStateRepository(session_factory)

    # 2. 构造初始状态对象
    state=RunState.create(
        thread_id="thread-repository-smoke",
        goal="测试 RunStateRepository",
        max_steps=10,
    )

    # 3. 验证【新增】：写入一条运行记录
    created=repository.create(state)
    print(f"created={created.run_id} status={created.status.value}")

    # 4. 验证【更新】：修改运行状态、当前节点、步数
    updated=repository.update_runtime_position(
        run_id=state.run_id,
        status=RunStatus.RUNNING,
        current_node="call_model",
        step_count=1,
    )
    if updated is None:
        raise RuntimeError("更新失败")
    print(f"updated_status={updated.status.value} node={updated.current_node}")

    # 5. 验证【主键查询】：读取单条记录
    loaded=repository.get_summary(state.run_id)
    if loaded is None:
        raise RuntimeError("读取失败")
    print(f"loaded_status={loaded.status.value} node={loaded.current_node}")

    # 6. 验证【条件查询】：按线程ID查列表
    thread_runs=repository.list_by_thread("thread-repository-smoke")
    print(f"thread_run_count={len(thread_runs)}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
    
