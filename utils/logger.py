"""
utils/logger.py
Coloured console + rotating file logger.
Forces UTF-8 on stdout to prevent Windows cp1252 crashes on box chars / emoji.
"""
import os
import sys
from loguru import logger
from config.settings import settings

# Force UTF-8 on Windows consoles so box chars and emoji don't crash print()
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.makedirs("logs", exist_ok=True)
logger.remove()
logger.add(
    sys.stdout,
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
    encoding="utf-8",
)
