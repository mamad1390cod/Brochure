"""
Logging module for Bot-File-School.
Combines Python logging with database audit logs.
"""

import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIRECTORY / "bot.log"
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LEVEL = getattr(logging, _LOG_LEVEL, logging.INFO)
if not isinstance(_LEVEL, int):
    _LEVEL = logging.INFO


class _SecretRedactionFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self._secret = os.getenv("BOT_TOKEN", "")

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secret:
            return True
        record.msg = record.getMessage().replace(self._secret, "[REDACTED]")
        record.args = ()
        if record.exc_info:
            formatter = logging.Formatter()
            record.exc_text = formatter.formatException(record.exc_info).replace(
                self._secret, "[REDACTED]"
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = record.exc_text.replace(self._secret, "[REDACTED]")
        return True


def setup_logger(name: str = "bot_file_school") -> logging.Logger:
    """Configure persistent and console logging for the application and libraries."""
    root = logging.getLogger()
    root.setLevel(_LEVEL)
    if not any(getattr(handler, "_bot_file_school_handler", False)
               for handler in root.handlers):
        LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        handlers = [
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            ),
        ]
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        redaction_filter = _SecretRedactionFilter()
        for handler in handlers:
            handler.setLevel(_LEVEL)
            handler.setFormatter(formatter)
            handler.addFilter(redaction_filter)
            handler._bot_file_school_handler = True
            root.addHandler(handler)

    logger = logging.getLogger(name)
    logger.setLevel(_LEVEL)
    logger.propagate = True
    return logger


# Global logger instance
logger = setup_logger()
