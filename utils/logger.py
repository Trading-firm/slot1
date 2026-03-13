"""
utils/logger.py
───────────────
Centralised logging using loguru.
Logs to both console and rotating file.
"""

import sys
import os
from loguru import logger
from config.settings import settings


def setup_logger():
    """Configure logger with console + file output."""

    # Remove default handler
    logger.remove()

    # Console handler — coloured, readable
    logger.add(
        sys.stdout,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level=settings.LOG_LEVEL,
    )

    # File handler — rotating, keeps 7 days of logs
    os.makedirs("logs", exist_ok=True)
    logger.add(
        settings.LOG_FILE,
        rotation="1 day",
        retention="7 days",
        compression="zip",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=settings.LOG_LEVEL,
    )

    return logger


# Initialise on import
setup_logger()

__all__ = ["logger"]
