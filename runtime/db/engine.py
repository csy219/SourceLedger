### 一、整体关系先理清楚

# 先搞懂三个核心概念的层级，后面就不会乱：

# 1. **Engine（引擎）**：底层连接池的入口，全局只创建一次，管理所有数据库连接的复用、生命周期。
# 2. **sessionmaker（会话工厂）**：绑定引擎的工厂，全局一个，用来生成每次操作的 Session。
# 3. **Session（会话）**：每次数据库操作拿一个会话，对应一个事务，用完就关闭，线程不安全，不能全局共用.


from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from runtime.db.config import DatabaseConfig

# 创建一个 SQLAlchemy Engine。
# Engine 不直接代表一条数据库连接，而是连接池的管理器：
# 需要连接时从池中拿
# 使用完还回池
# 连接失效时自动重建或检查
def create_db_engine(
        config:DatabaseConfig | None = None,
)->Engine:
    # 如果没有传入 DatabaseConfig，就从环境变量读取
    resolved=config or DatabaseConfig.from_env()

    # resolved.url     PostgreSQL 连接地址
    # echo            是否打印 SQL
    # pool_pre_ping   连接使用前先检测是否仍然有效
    return create_engine(
        resolved.url,
        echo=resolved.echo,
        # pool_pre_ping=True 很重要，因为数据库长期运行后可能出现连接被服务端关闭，但客户端连接池不知道的情况。
        pool_pre_ping=True,
    )

# 它返回一个 Session 工厂。
# Session 是 SQLAlchemy 的工作单元：
# 添加对象
# 修改对象
# 查询对象
# 提交事务
# 回滚事务
def create_session_factory(
    engine: Engine,
):
    # bind=engine              Session 使用哪个连接池
    # autoflush=False          查询前不自动 flush
    # expire_on_commit=False   commit 后对象属性不立即过期
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )