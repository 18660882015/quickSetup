"""
全局配置管理

使用 pydantic-settings BaseSettings 读取 .env 文件，提供配置单例。
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录（mvp-agent/）
BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

# 运行时数据目录
DATA_DIR: Path = BASE_DIR / "data"
DB_DIR: Path = DATA_DIR / "db"
DEPLOYMENTS_DIR: Path = DATA_DIR / "deployments"
BACKUPS_DIR: Path = DATA_DIR / "backups"
LOGS_DIR: Path = DATA_DIR / "logs"


class Settings(BaseSettings):
    """应用配置，从 .env 文件读取"""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AES 加密密钥（Fernet 格式，base64 编码的 32 字节）
    aes_secret_key: str = Field(
        default="",
        description="Fernet AES 加密密钥",
    )

    # JWT 签名密钥
    jwt_secret: str = Field(
        default="mvp-default-jwt-secret-change-me",
        description="JWT 签名密钥",
    )

    # DeepSeek API Key
    deepseek_api_key: str = Field(
        default="",
        description="DeepSeek API Key",
    )

    # SQLite 数据库路径
    db_path: str = Field(
        default="data/db/mvp.db",
        description="SQLite 数据库文件路径",
    )

    # 服务端口
    app_port: int = Field(default=8080, description="服务监听端口")

    # 是否开发模式
    debug: bool = Field(default=True, description="是否开发模式")

    # 固定管理员账号
    admin_username: str = Field(default="admin", description="管理员用户名")
    admin_password: str = Field(default="admin123", description="管理员密码")

    # JWT 过期时间（小时）
    jwt_expire_hours: int = Field(default=24, description="JWT 过期时间（小时）")

    def _resolve_db_path(self) -> str:
        """解析数据库文件绝对路径

        如果 db_path 是绝对路径且不在项目目录内（可能被系统环境变量覆盖），
        则回退到项目默认路径 data/db/mvp.db。
        """
        db_file = self.db_path
        if os.path.isabs(db_file):
            # 检查绝对路径是否在项目目录内
            try:
                Path(db_file).resolve().relative_to(BASE_DIR.resolve())
            except ValueError:
                # 不在项目目录内，回退到默认路径
                db_file = "data/db/mvp.db"
        if not os.path.isabs(db_file):
            db_file = str(BASE_DIR / db_file)
        return db_file

    @property
    def db_url(self) -> str:
        """SQLite 数据库 URL"""
        db_file = self._resolve_db_path()
        # 确保目录存在
        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        # 使用正斜杠避免 Windows 路径问题
        db_file = db_file.replace("\\", "/")
        return f"sqlite:///{db_file}"

    @property
    def db_file_path(self) -> str:
        """数据库文件绝对路径"""
        return self._resolve_db_path()


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


def ensure_runtime_dirs():
    """确保运行时目录存在"""
    for d in (DATA_DIR, DB_DIR, DEPLOYMENTS_DIR, BACKUPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
