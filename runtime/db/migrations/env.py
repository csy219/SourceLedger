from logging.config import fileConfig

# context              Alembic 当前迁移上下文
# engine_from_config  根据配置创建数据库 Engine
# pool.NullPool        迁移只创建少量连接，不保留长期连接池
from alembic import context
from sqlalchemy import engine_from_config, pool

from runtime.db.config import DatabaseConfig
# 3. 绑定 ORM 模型
from runtime.db.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 这一步把：
# agent-learningstage1/.env
# 里的：
# DATABASE_URL
# 读取出来，覆盖 alembic.ini 中的占位 URL。
# 3. 绑定 ORM 模型
database_config = DatabaseConfig.from_env()
config.set_main_option(
    "sqlalchemy.url",
    database_config.url,
)

target_metadata = Base.metadata

# 4. 离线模式
# 不连接数据库，只生成 SQL。
# 当前阶段主要使用在线模式。
def run_migrations_offline() -> None:
    context.configure(
        url=database_config.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()

# 5. 在线模式
# 创建真实数据库连接。
# compare_type=True 让 Alembic 在自动比较时检测字段类型变化。
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(
            config.config_ini_section,
            {},
        ),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

# 6. 启动迁移
# 根据 Alembic 运行参数自动选择模式。
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()