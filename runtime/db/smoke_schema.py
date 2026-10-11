# 这段脚本就是一个**轻量级冒烟测试**，目的只有一个：
# > 
# > 不依赖真实 PostgreSQL，只用 SQLite 快速验证：你写的 ORM 模型语法没错、表能正常创建、数据能正常插入和查询。

# 跑通了就说明 S16-1 的 schema 设计是合格的，后面换成 PostgreSQL 只需要改连接地址，模型代码不用动。

import sys
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))


# - `create_engine`：创建数据库连接引擎，相当于和数据库建立连接的入口。
# - `inspect`：用来检查数据库里的真实信息，比如有哪些表。
# - `select`：SQLAlchemy 2.0 的查询构造器，用来写查询语句。
# - `Session`：数据库会话，所有增删改查都在会话里执行，自动管理连接和事务。
# - 下面四个类 + `Base`：就是你在 `models.py` 里定义的 ORM 模型和基类。
from sqlalchemy import(
    create_engine,
    inspect,
    select,
)
from sqlalchemy.orm import Session

from runtime.db.models import (
    Base,
    CheckpointRow,
    IdempotencyKeyRow,
    RunRow,
    ToolCallRow,
)

def main()->int:

#     - 用的是 **SQLite 内存数据库**（`:memory:`），数据只存在内存里，程序结束就消失，完全不需要安装启动数据库，专门用来快速测试表结构。
# - `future=True`：开启 SQLAlchemy 2.0 语法模式，统一用新版 API。
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
    )
#     - 这是 ORM 的核心能力：**根据你写的 Python 模型类，自动生成 `CREATE TABLE` 语句并执行**。
# - 不用你手写任何 SQL，`models.py` 里四个类对应的四张表，这一行就全部建好了。
    Base.metadata.create_all(engine)


# - `with Session(engine)`：会话上下文，自动管理连接，退出时自动关闭，不用手动关。
# - 每个 `xxxRow(...)`：创建一个模型对象，就对应数据库里的**一行数据**，参数对应表里的每一列。
# - `session.add_all()`：把这 4 个对象加入会话，只是 “暂存”，还没真正写到数据库里。
# - `session.commit()`：提交事务，真正把数据写入数据库。如果中间报错，事务会回滚，不会写进去一半。
    with Session(engine) as session:
        run = RunRow(
            run_id="run-1",
            thread_id="thread-1",
            goal="检查仓库并修复 CI 失败",
            status="running",
            current_node="execute_tool",
            step_count=1,
            max_steps=20,
        )
        checkpoint = CheckpointRow(
            run_id="run-1",
            version=1,
            node="after_tool",
            state_snapshot={
                "status": "running",
                "step_count": 1,
            },
        )
        tool_call = ToolCallRow(
            run_id="run-1",
            tool_call_id="call-1",
            tool_name="shell.run",
            arguments={"command": "pytest -q"},
            status="succeeded",
            attempt=1,
            max_attempts=3,
            result={"exit_code": 0},
        )
        idempotency = IdempotencyKeyRow(
            key="run-1:call-1",
            run_id="run-1",
            status="succeeded",
            result={"exit_code": 0},
        )

        session.add_all(
            [
                run,
                checkpoint,
                tool_call,
                idempotency,
            ]
        )
        session.commit()

        run_id = session.scalar(
            select(RunRow.run_id)
        )
        checkpoint_count = session.query(
            CheckpointRow
        ).count()
        tool_call_count = session.query(
            ToolCallRow
        ).count()
        idempotency_count = session.query(
            IdempotencyKeyRow
        ).count()

        print(
            "tables=",
            sorted(
                inspect(engine).get_table_names()
            ),
        )
        print(f"run_id={run_id}")
        print(
            f"checkpoint_count={checkpoint_count}"
        )
        print(
            f"tool_call_count={tool_call_count}"
        )
        print(
            "idempotency_count="
            f"{idempotency_count}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
