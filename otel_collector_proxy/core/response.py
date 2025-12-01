import typing

import structlog
from fastapi import status
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, Response

from otel_collector_proxy.core.config import settings

logger: structlog.BoundLogger = structlog.get_logger()


class MaskedResponse(Response):
    async def __call__(
        self, scope: typing.MutableMapping[str, typing.Any], receive: typing.Any, send: typing.Any
    ) -> None:
        if settings.ENVIRONMENT.is_production:
            logger.info(
                "Masking response in production",
                original_status_code=self.status_code,
                original_body_length=len(self.body),
            )
            self.status_code = status.HTTP_204_NO_CONTENT
            self.body = b""
            self.init_headers()  # Re-initialize headers to update Content-Length
            self.headers.append(key="x-m-r", value="1")

        await super().__call__(scope, receive, send)


class SecureJSONResponse(MaskedResponse, JSONResponse):
    def __init__(
        self,
        content: typing.Any,
        status_code: int = 200,
        headers: typing.Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        super().__init__(content, status_code, headers, media_type, background)
