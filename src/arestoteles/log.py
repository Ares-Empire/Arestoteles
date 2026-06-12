"""structlog setup: pretty console for TTYs, JSON lines for the server/journald."""

import logging
import os
import sys

import structlog


def setup_logging(level: str | None = None) -> None:
    log_level = getattr(logging, (level or os.environ.get("LOG_LEVEL", "INFO")).upper())

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    use_json = os.environ.get("LOG_FORMAT", "").lower() == "json" or not sys.stderr.isatty()
    renderer: structlog.typing.Processor
    if use_json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
