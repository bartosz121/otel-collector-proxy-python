import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI

from otel_collector_proxy.core.middleware.logging import LoggingMiddleware
from otel_collector_proxy.core.middleware.prometheus import PrometheusMiddleware
from otel_collector_proxy.core.middleware.request_id import RequestIdMiddleware

if TYPE_CHECKING:
    from otel_collector_proxy.core.config import Environment


def configure(app: FastAPI, environment: Environment) -> None:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger()

    app.add_middleware(
        RequestIdMiddleware,
        header_name="x-request-id",
        id_factory=lambda _: str(uuid.uuid4()),
    )

    if not environment.is_testing:
        logger.info("Prometheus middleware enabled")
        app.add_middleware(PrometheusMiddleware)

    app.add_middleware(LoggingMiddleware)
