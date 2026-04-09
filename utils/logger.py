"""
utils/logger.py
───────────────
Coloured console + rotating file logger.
"""
import os
from loguru import logger
from config.settings import settings

os.makedirs("logs", exist_ok=True)
logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level:<8}</level> | "
           "<cyan>{module}</cyan>:<cyan>{line}</cyan> | "
           "<level>{message}</level>",
    level=settings.LOG_LEVEL,
    colorize=True,
)
logger.add(
    settings.LOG_FILE,
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}:{line} | {message}",
)
