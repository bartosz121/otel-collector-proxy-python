# pyright: reportUnusedFunction=false

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, TypedDict, cast

import httpx
import structlog
from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware

from otel_collector_proxy.core.config import settings
from otel_collector_proxy.core.data_type import DataType
from otel_collector_proxy.core.exception_handlers import configure as configure_exception_handlers
from otel_collector_proxy.core.exceptions import BadRequest, ErrorCode, ResponseValidationError
from otel_collector_proxy.core.logging import configure as configure_logging
from otel_collector_proxy.core.middleware.configure import configure as configure_middleware
from otel_collector_proxy.core.rate_limit import RateLimiter as RateLimiter_
from otel_collector_proxy.core.response import MaskedResponse

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


class State(TypedDict):
    rate_limiter: RateLimiter_
    otel_collector_client: httpx.AsyncClient  # Opentelemetry sdk (json/protobuf)
    otel_collector_faro_client: httpx.AsyncClient  # Faro


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[State]:
    async with AsyncExitStack() as stack:
        rate_limiter = RateLimiter_(settings.RATE_LIMIT_REQUESTS, settings.RATE_LIMIT_WINDOW)

        otel_http_client = await stack.enter_async_context(
            httpx.AsyncClient(base_url=settings.OTEL_COLLECTOR_HOST)
        )
        otel_faro_client = await stack.enter_async_context(
            httpx.AsyncClient(base_url=settings.OTEL_COLLECTOR_FARO_HOST)
        )

        yield {
            "rate_limiter": rate_limiter,
            "otel_collector_client": otel_http_client,
            "otel_collector_faro_client": otel_faro_client,
        }


@dataclass
class DataReceiver:
    client: httpx.AsyncClient
    endpoint_url: str


def get_otel_collector_receiver(request: Request) -> DataReceiver:
    # https://github.com/Kludex/starlette/pull/3036
    client = cast(httpx.AsyncClient, request.state.otel_collector_client)
    return DataReceiver(client=client, endpoint_url=settings.OTEL_COLLECTOR_ENDPOINT)


def get_otel_collector_faro_receiver(request: Request) -> DataReceiver:
    # https://github.com/Kludex/starlette/pull/3036
    client = cast(httpx.AsyncClient, request.state.otel_collector_faro_client)
    return DataReceiver(client=client, endpoint_url=settings.OTEL_COLLECTOR_FARO_ENDPOINT)


def get_rate_limiter(request: Request) -> RateLimiter_:
    # https://github.com/Kludex/starlette/pull/3036
    return cast(RateLimiter_, request.state.rate_limiter)


OtelDataReceiver = Annotated[DataReceiver, Depends(get_otel_collector_receiver)]
FaroDataReceiver = Annotated[DataReceiver, Depends(get_otel_collector_faro_receiver)]
RateLimiter = Annotated[RateLimiter_, Depends(get_rate_limiter)]


def get_otel_client(
    otel_receiver: OtelDataReceiver,
    faro_receiver: FaroDataReceiver,
    x_data_type: Annotated[str | None, Header()] = None,
) -> DataReceiver:
    match x_data_type:
        case DataType.OPENTELEMETRY_SDK.value:
            return otel_receiver
        case DataType.FARO.value:
            return faro_receiver
        case _:
            raise BadRequest(code=ErrorCode.UNEXPECTED_DATA_TYPE, error="Unexpected data type")


DataReceiverDep = Annotated[DataReceiver, Depends(get_otel_client)]


def create_app() -> FastAPI:
    configure_logging(settings.ENABLED_LOGGERS)

    app = FastAPI(
        lifespan=lifespan,
        docs_url="/docs" if settings.ENVIRONMENT.is_development else None,
        responses={
            422: {
                "description": "Response Validation Error",
                "model": ResponseValidationError,
            }
        },
    )

    configure_middleware(app, settings.ENVIRONMENT)
    configure_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    logger.info(f"{settings=!r}")
    logger.info(f"{settings.CORS_ORIGINS=!r}")

    @app.get("/")
    async def home() -> dict[str, str]:
        return {"msg": "ok"}

    @app.post("/api/v1/traces", status_code=status.HTTP_200_OK)
    async def traces(
        request: Request,
        background_tasks: BackgroundTasks,
        rate_limiter: RateLimiter,
        data_receiver: DataReceiverDep,
    ) -> MaskedResponse:
        client_ip = request.client.host if request.client else "unknown"

        logger.info("rate limiter state", state=repr(rate_limiter.storage))
        if not rate_limiter.is_allowed(client_ip):
            if settings.ENVIRONMENT.is_production:
                return MaskedResponse(content=b"", status_code=status.HTTP_204_NO_CONTENT)

            return MaskedResponse(
                content=b"Too Many Requests",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        content_length = request.headers.get("content-length")
        if content_length:
            if int(content_length) > settings.MAX_BODY_SIZE:
                return MaskedResponse(
                    content=b"Payload too large",
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )

        # We accept any body and forward it to the collector
        body = await request.body()

        if len(body) > settings.MAX_BODY_SIZE:
            return MaskedResponse(
                content=b"Payload too large",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )

        headers = dict(request.headers)

        # Filter headers if necessary, but for now forwarding most relevant ones
        # Host header should be updated by httpx usually
        forward_headers = {
            k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")
        }

        # Content-Type is important for the collector to know it's protobuf or json
        if "content-type" in headers:
            forward_headers["content-type"] = headers["content-type"]
        else:
            # Be defensive, reject if we don't know the content-type
            return MaskedResponse(
                content=b"Missing Content-Type header",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if settings.ENVIRONMENT.is_production:
            background_tasks.add_task(
                forward_traces,
                data_receiver.client,
                data_receiver.endpoint_url,
                body,
                forward_headers,
            )
            return MaskedResponse(content=b"", status_code=status.HTTP_204_NO_CONTENT)

        return await forward_traces(
            data_receiver.client,
            data_receiver.endpoint_url,
            body,
            forward_headers,
        )

    return app


async def forward_traces(
    client: httpx.AsyncClient, url: str, body: bytes, headers: dict[str, str]
) -> MaskedResponse:
    try:
        logger.debug(
            "sending request to otel collector",
            url=str(client.base_url),
            headers=headers,
        )
        response = await client.post(
            url,
            content=body,
            headers=headers,
        )
        logger.info("otel collector response", response=repr(response))
        logger.debug("otel collector response vars", response_vars=vars(response))

        # We return the status code from the collector
        return MaskedResponse(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type"),
        )
    except httpx.RequestError as exc:
        logger.error("Failed to forward traces to collector", error=str(exc))
        return MaskedResponse(
            content=b"Failed to forward traces",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
