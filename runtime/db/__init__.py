# | 概念 | 作用 |
# |---|---|
# | Table | 一张表，类似一个结构化文件 |
# | Row | 表中的一条记录 |
# | Column | 一条记录中的字段 |
# | Primary Key | 唯一标识一行，例如 `run_id` |
# | Foreign Key | 指向另一张表的主键，例如 `checkpoint.run_id -> runs.run_id` |
# | Unique Constraint | 禁止重复，例如同一个 run 不能有两个相同 `tool_call_id` |
# | Index | 加速查询，例如按 `thread_id` 查任务 |
# | JSON | 保存结构化快照，例如完整状态和工具结果 |
# | Transaction | 一组要么全部成功、要么全部回滚的数据库操作 |
# | Migration | 数据库结构的版本变更脚本 |

from runtime.db.models import(
    Base,
    CheckpointRow,
    IdempotencyKeyRow,
    RunRow,
    ToolCallRow,
)

__all__ = [
    "Base",
    "RunRow",
    "CheckpointRow",
    "ToolCallRow",
    "IdempotencyKeyRow",
]

