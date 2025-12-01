import time

from prometheus_client import Counter, Gauge, Histogram
from starlette.requests import Request
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUESTS = Counter(
    "otel_collector_proxy_requests_total",
    "Total count of requests by method and path",
    ["method", "path"],
)

RESPONSES = Counter(
    "otel_collector_proxy_responses_total",
    "Total count of responses by method, path and status code",
    ["method", "path", "status_code"],
)

REQUESTS_PROCESS_TIME = Histogram(
    "otel_collector_proxy_requests_process_time_seconds",
    "Histogram of requests process time by method, path and status code in seconds",
    ["method", "path", "status_code"],
)

EXCEPTIONS = Counter(
    "otel_collector_proxy_exceptions_total",
    "Total count of exceptions raised by method, path and exception type",
    ["method", "path", "exception_type"],
)
REQUESTS_IN_PROGRESS = Gauge(
    "otel_collector_proxy_requests_in_progress",
    "Gauge of requests currently being processed by method and path",
    ["method", "path"],
)


class PrometheusMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def get_route_path_string(request: Request) -> str:
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return route.path
        return request.url.path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http"}:
            await self.app(scope, receive, send)
            return

        t0 = time.perf_counter()

        status_code = "418"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                nonlocal status_code
                status_code = str(message["status"])
            await send(message)

        request = Request(scope)
        method = request.method
        path = self.get_route_path_string(request)

        REQUESTS_IN_PROGRESS.labels(method=method, path=path).inc()
        REQUESTS.labels(method=method, path=path).inc()

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            status_code = "500"
            EXCEPTIONS.labels(method=method, path=path, exception_type=type(exc).__name__).inc()
            raise exc
        else:
            duration = time.perf_counter() - t0
            REQUESTS_PROCESS_TIME.labels(
                method=method, path=path, status_code=status_code
            ).observe(duration)
        finally:
            RESPONSES.labels(method=method, path=path, status_code=status_code).inc()
            REQUESTS_IN_PROGRESS.labels(method=method, path=path).dec()
