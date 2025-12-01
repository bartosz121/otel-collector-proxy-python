"""
https://www.structlog.org/en/stable/standard-library.html#rendering-using-structlog-based-formatters-within-logging
"""

import logging
import logging.config
from typing import Any

import structlog

from otel_collector_proxy.core.config import Environment, settings


def _get_renderer(environment: Environment) -> Any:
    if environment.is_production:
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer(colors=True)


def _configure_std_logging(loggers: list[str]) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "otel_collector_proxy": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        _get_renderer(settings.ENVIRONMENT),
                    ],
                    "foreign_pre_chain": [
                        structlog.contextvars.merge_contextvars,
                        structlog.stdlib.add_log_level,
                        structlog.stdlib.add_logger_name,
                        structlog.stdlib.PositionalArgumentsFormatter(),
                        structlog.stdlib.ExtraAdder(),
                        structlog.processors.TimeStamper(fmt="iso", utc=True),
                        structlog.processors.UnicodeDecoder(),
                        structlog.processors.StackInfoRenderer(),
                        structlog.processors.format_exc_info,
                    ],
                },
            },
            "handlers": {
                "default": {
                    "level": settings.LOG_LEVEL,
                    "class": "logging.StreamHandler",
                    "formatter": "otel_collector_proxy",
                },
            },
            "loggers": {
                "": {
                    "handlers": ["default"],
                    "level": settings.LOG_LEVEL,
                    "propagate": False,
                },
                **{
                    logger: {
                        "handlers": [],
                        "propagate": True,
                    }
                    for logger in loggers
                },
            },
        }
    )


def _configure_structlog():
    structlog.configure_once(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.UnicodeDecoder(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def configure(loggers: list[str]):
    _configure_std_logging(loggers)
    _configure_structlog()


__all__ = ("configure",)
