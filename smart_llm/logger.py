"""Structured logging for Smart LLM with daily rotation and configurable retention."""

import logging
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logger(
    name: str = "smart_llm",
    log_dir: str | None = None,
    retention_days: int = 7,
    level: int = logging.INFO,
) -> logging.Logger:
    """Create a logger with console output and optional file rotation.

    Args:
        name: Logger name (default "smart_llm")
        log_dir: Directory for log files. If None, only console logging.
        retention_days: How many days of log files to keep (default 7)
        level: Logging level (default INFO)

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Already configured — avoid duplicate handlers

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler with daily rotation
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            os.path.join(log_dir, "smart_llm.log"),
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
