import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from runtime.db.engine import create_db_engine


def main() -> int:

    # 2. 创建 Engine
    # engine = create_db_engine()
    # 它会读取：
    # DATABASE_URL
    # DATABASE_ECHO
    # 并创建 SQLAlchemy Engine。
    engine = create_db_engine()

    # 3. 真正建立连接
    # with engine.connect() as connection:
    # 之前创建 Engine 时不一定连接数据库。
    # 只有调用：
    # engine.connect()
    # 才会真正从连接池取一条数据库连接。
    with engine.connect() as connection:

        # SELECT 1 是 PostgreSQL 最小连接测试：
        # 数据库能执行 SQL
        # 连接有效
        # 驱动配置正确
        
        # 如果成功，结果就是：
        # 1
        value = connection.scalar(
            text("SELECT 1")
        )
        print(f"database_connection={value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())