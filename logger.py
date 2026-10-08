"""
Logging module for Bot-File-School.
Combines Python logging with database audit logs.
"""

import logging
import sys
from config import LOG_LEVEL


def setup_logger(name: str = "bot_file_school") -> logging.Logger:
    """Set up and return the application logger."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)

    return logger


# Global logger instance
logger = setup_logger()
