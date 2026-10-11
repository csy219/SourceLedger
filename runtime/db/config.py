# 这段是 S16-2 里的**数据库配置管理模块**，核心作用是把数据库连接参数从代码里抽离出来，
# 支持通过环境变量灵活配置，同时保留本地开发默认值，是后续创建数据库连接、连接池的基础

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT=Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")

# 这是 SQLAlchemy 标准的**数据库连接 URL**，格式固定为：
# 方言+驱动://用户名:密码@主机:端口/数据库名
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://"
    "agent:agent_password"
    "@localhost:5433/"
    "agent_runtime"
)


@dataclass(frozen=True)
class DatabaseConfig:
#     两个属性的作用：
# - `url`：数据库连接地址
# - `echo`：是否打印 SQL 语句。设为 `True` 时，SQLAlchemy 会把所有执行的 SQL 都输出到控制台，
# 调试表结构、优化查询时非常有用；生产环境默认关闭。
    url:str
    echo:bool

    @classmethod
    def from_env(
        cls,
    )->"DatabaseConfig":
        # 这是工厂方法，从系统环境变量里读取配置，生成 `DatabaseConfig` 对象：
        # 1. **读取连接地址**：优先读环境变量 `DATABASE_URL`，没有就回退到本地默认值。
        # 2. **读取 echo 开关**：优先读环境变量 `DATABASE_ECHO`，默认 `false`；转成小写再判断，兼容 `True`/`true`/`FALSE`/`false` 各种写法。
        # 3. 返回构建好的只读配置对象。
        url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        echo = os.getenv("DATABASE_ECHO", "false").lower() == "true"
        return cls(url=url, echo=echo)