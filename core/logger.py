"""
Logging configuration for SIAT Agent.

This module provides centralized logging setup with proper formatting,
file rotation, and console output.
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .settings import settings, BASE_DIR


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up a logger with both file and console handlers.

    Args:
        name: Logger name (typically __name__ of the calling module)
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers if logger already configured
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Create logs directory if it doesn't exist
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    # Format for log messages
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler (INFO and above)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler with rotation (DEBUG and above)
    file_handler = RotatingFileHandler(
        log_dir / "siat_agent.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Error file handler (ERROR and above only)
    error_handler = RotatingFileHandler(
        log_dir / "siat_agent_errors.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    return logger


# Create a default logger for the application
logger = setup_logger("siat_agent")