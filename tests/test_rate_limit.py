from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
import respx
from asgi_lifespan import LifespanManager
from fastapi import status

from otel_collector_proxy.core.config import Environment, settings
from otel_collector_proxy.core.rate_limit import RateLimiter
from otel_collector_proxy.main import create_app, get_rate_limiter


def test_rate_limiter_logic(monkeypatch: pytest.MonkeyPatch):
    t = [0.0]

    def fake_monotonic() -> float:
        return t[0]

    import otel_collector_proxy.core.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module.time, "monotonic", fake_monotonic)

    limiter = RateLimiter(requests_limit=2, window_seconds=1)

    assert limiter.is_allowed("1.2.3.4") is True
    assert limiter.is_allowed("1.2.3.4") is True
    assert limiter.is_allowed("1.2.3.4") is False

    assert limiter.is_allowed("5.6.7.8") is True

    t[0] += 1.1
    assert limiter.is_allowed("1.2.3.4") is True


def test_rate_limiter_cleanup(monkeypatch: pytest.MonkeyPatch):
    t = [0.0]

    def fake_monotonic() -> float:
        return t[0]

    import otel_collector_proxy.core.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module.time, "monotonic", fake_monotonic)

    limiter = RateLimiter(requests_limit=2, window_seconds=1)

    limiter.is_allowed("1.2.3.4")
    limiter.is_allowed("5.6.7.8")
    assert len(limiter.storage) == 2

    t[0] += 15
    limiter.is_allowed("9.9.9.9")

    assert "1.2.3.4" not in limiter.storage
    assert "5.6.7.8" not in limiter.storage
    assert "9.9.9.9" in limiter.storage


@pytest_asyncio.fixture
async def dev_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient]:
    monkeypatch.setattr(
        "otel_collector_proxy.core.config.settings.ENVIRONMENT", Environment.DEVELOPMENT
    )
    app = create_app()
    new_limiter = RateLimiter(requests_limit=1, window_seconds=60)
    app.dependency_overrides[get_rate_limiter] = lambda: new_limiter

    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            yield client


@pytest_asyncio.fixture
async def prod_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient]:
    monkeypatch.setattr(
        "otel_collector_proxy.core.config.settings.ENVIRONMENT", Environment.PRODUCTION
    )
    app = create_app()
    new_limiter = RateLimiter(requests_limit=1, window_seconds=60)
    app.dependency_overrides[get_rate_limiter] = lambda: new_limiter

    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            yield client


@respx.mock
async def test_rate_limit_development(dev_client: httpx.AsyncClient):
    """In DEVELOPMENT, exceeding rate limit returns 429."""
    otel_route = respx.post(f"{settings.OTEL_COLLECTOR_HTTP_HOST}/v1/traces").mock(
        return_value=httpx.Response(200, content=b"OK")
    )

    response = await dev_client.post(
        "/api/v1/traces",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert otel_route.call_count == 1

    response = await dev_client.post(
        "/api/v1/traces",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.content == b"Too Many Requests"
    assert otel_route.call_count == 1


@respx.mock
async def test_rate_limit_production(prod_client: httpx.AsyncClient):
    """In PRODUCTION, exceeding rate limit returns 204."""
    otel_route = respx.post(f"{settings.OTEL_COLLECTOR_HTTP_HOST}/v1/traces").mock(
        return_value=httpx.Response(200, content=b"OK")
    )

    response = await prod_client.post(
        "/api/v1/traces",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert otel_route.call_count == 1

    response = await prod_client.post(
        "/api/v1/traces",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b""
    assert otel_route.call_count == 1
