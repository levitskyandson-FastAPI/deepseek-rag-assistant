import sys
from loguru import logger
from config import settings

def setup_logger(level: str = "INFO"):
    """Настройка логгера Loguru"""
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add(
        "logs/assistant.log",
        rotation="10 MB",
        retention="30 days",
        level="DEBUG",
        compression="zip"
    )
    return logger