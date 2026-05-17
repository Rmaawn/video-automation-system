"""Logging setup with file rotation and console output."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import settings


def setup_logger(name: str) -> logging.Logger:
    """Create a logger with both file and console handlers."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    log_level = settings.get("app.log_level", "INFO")
    log_dir = Path(settings.get("app.log_dir", "output/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / "video_automation.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
