"""
日志模块配置
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.config.settings import get_settings

settings = get_settings()

_logger_initialized = False


def setup_logger() -> logging.Logger:
    """初始化全局日志配置"""
    global _logger_initialized
    if _logger_initialized:
        return logging.getLogger("wealth_manager")

    logger = logging.getLogger("wealth_manager")
    logger.setLevel(getattr(logging, settings.log.level.upper(), logging.INFO))

    # 格式
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    log_file = Path(settings.log.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.log.max_bytes,
        backupCount=settings.log.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _logger_initialized = True
    return logger


def get_logger(name: str = "wealth_manager") -> logging.Logger:
    """获取模块级日志实例"""
    if not _logger_initialized:
        setup_logger()
    return logging.getLogger(name)
