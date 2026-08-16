"""
sys_configs 表 - 系统配置 + 种子数据初始化
"""
from datetime import datetime
from typing import List

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.orm import sessionmaker

from app.models.database import Base


class SysConfig(Base):
    """系统配置表"""

    __tablename__ = "sys_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), nullable=False, unique=True, comment="配置键")
    config_value = Column(Text, nullable=True, comment="配置值")
    is_encrypted = Column(Boolean, nullable=False, default=False, comment="是否加密")
    description = Column(String(255), nullable=True, comment="描述")
    updated_at = Column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )

    def __repr__(self):
        return f"<SysConfig(key={self.config_key})>"


# 种子配置定义：(key, value, is_encrypted, description)
SEED_CONFIGS: List[tuple] = [
    # AI 相关
    ("deepseek_api_key", "", True, "DeepSeek API Key"),
    ("deepseek_base_url", "https://api.deepseek.com", False, "DeepSeek API 地址"),
    ("deepseek_model", "deepseek-chat", False, "DeepSeek 模型名称"),

    # 钉钉相关
    ("dingtalk_webhook", "", True, "钉钉机器人 Webhook URL"),
    ("dingtalk_secret", "", True, "钉钉机器人签名密钥"),
    ("dingtalk_enabled", "false", False, "是否启用钉钉通知"),

    # 监控相关
    ("monitor_time", "02:00", False, "每日监控报告时间"),
    ("cpu_threshold", "80", False, "CPU 告警阈值(%)"),
    ("memory_threshold", "80", False, "内存告警阈值(%)"),
    ("disk_threshold", "90", False, "磁盘告警阈值(%)"),

    # 部署相关
    ("backup_max_count", "5", False, "最大保留备份数量"),
    ("deploy_timeout", "300", False, "部署超时时间(秒)"),
]


def seed_sys_configs(session_factory: sessionmaker):
    """插入种子配置数据（已存在则跳过）"""
    db = session_factory()
    try:
        for key, value, is_encrypted, description in SEED_CONFIGS:
            existing = db.query(SysConfig).filter(SysConfig.config_key == key).first()
            if existing is None:
                config = SysConfig(
                    config_key=key,
                    config_value=value,
                    is_encrypted=is_encrypted,
                    description=description,
                )
                db.add(config)

        # 如果 .env 中有 deepseek_api_key，初始化到 sys_configs（加密存储）
        from app.config.settings import get_settings
        from app.utils.crypto import encrypt_value
        settings = get_settings()
        if settings.deepseek_api_key:
            config = db.query(SysConfig).filter(SysConfig.config_key == "deepseek_api_key").first()
            if config and not config.config_value:
                config.config_value = encrypt_value(settings.deepseek_api_key)

        db.commit()
        print(f"[seed] 系统配置种子数据已插入 ({len(SEED_CONFIGS)} 条)")
    except Exception as e:
        db.rollback()
        print(f"[seed] 种子数据插入失败: {e}")
        raise
    finally:
        db.close()


def get_config_value(db, key: str, default: str = "") -> str:
    """读取配置值（自动解密）"""
    from app.utils.crypto import decrypt_value
    config = db.query(SysConfig).filter(SysConfig.config_key == key).first()
    if config is None:
        return default
    if config.is_encrypted and config.config_value:
        return decrypt_value(config.config_value)
    return config.config_value or default


def set_config_value(db, key: str, value: str, encrypt: bool = False):
    """写入配置值（自动加密）"""
    from app.utils.crypto import encrypt_value
    config = db.query(SysConfig).filter(SysConfig.config_key == key).first()
    if config is None:
        config = SysConfig(
            config_key=key,
            config_value=encrypt_value(value) if encrypt else value,
            is_encrypted=encrypt,
        )
        db.add(config)
    else:
        config.config_value = encrypt_value(value) if encrypt else value
        config.is_encrypted = encrypt
    db.commit()
    return config
