"""
日志配置
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app.config.settings import get_settings, LOGS_DIR


def setup_logger(name: str = "mvp", level: int = None) -> logging.Logger:
    """配置并返回日志器"""
    settings = get_settings()
    if level is None:
        level = logging.DEBUG if settings.debug else logging.INFO

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOGS_DIR / "mvp-agent.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[logger] 文件日志初始化失败: {e}")

    return logger


def get_logger(name: str = "mvp") -> logging.Logger:
    """获取日志器（如果未初始化则自动初始化）"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
