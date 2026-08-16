"""
SQLAlchemy 数据库引擎与会话管理

- SQLite + check_same_thread=False
- WAL 模式提升并发读写
- get_db 依赖注入
- init_database 建表 + 种子数据
"""
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config.settings import get_settings, ensure_runtime_dirs


# 确保运行时目录存在
ensure_runtime_dirs()

settings = get_settings()

# 创建引擎
engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False},
    echo=False,
    pool_pre_ping=True,
)

# 会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# 声明式基类
Base = declarative_base()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 连接时设置 PRAGMA：WAL 模式 + 外键约束"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """上下文管理器：获取数据库会话（非 FastAPI 场景使用）"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_database():
    """初始化数据库：建表 + 插入种子数据"""
    # 导入所有模型，确保表被注册
    from app.models import host, deploy_record, monitor_daily, sys_config  # noqa: F401

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # 插入种子数据
    from app.models.sys_config import seed_sys_configs
    seed_sys_configs(SessionLocal)

    # 确保数据目录存在
    from app.config.settings import DEPLOYMENTS_DIR, BACKUPS_DIR, LOGS_DIR
    for d in (DEPLOYMENTS_DIR, BACKUPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    print(f"[database] 初始化完成: {settings.db_file_path}")
