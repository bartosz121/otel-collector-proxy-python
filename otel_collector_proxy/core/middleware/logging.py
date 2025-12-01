import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from otel_collector_proxy.core.middleware.request_id import request_id_ctx


class LoggingMiddleware:
    app: ASGIApp

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id_ctx.get(),
            method=scope["method"],
            path=scope["path"],
        )

        await self.app(scope, receive, send)
