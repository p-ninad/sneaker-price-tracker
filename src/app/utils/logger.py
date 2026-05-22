"""Structured logging configuration."""

import logging
import sys
from typing import Any
import structlog
from app.config import settings


def setup_logging() -> None:
    """Configure structured logging with structlog + stdlib."""

    # Stdlib config
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )

    # Structlog config
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.typing.WrappedLogger:
    """Get a logger instance."""
    return structlog.get_logger(name)


class LogContextManager:
    """Context manager for logging with structured context."""

    def __init__(self, **context: Any):
        self.context = context
        self.logger = get_logger("app")

    def __enter__(self):
        for key, value in self.context.items():
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(**{key: value})
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        structlog.contextvars.clear_contextvars()
