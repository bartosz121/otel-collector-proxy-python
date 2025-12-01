from collections.abc import AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from fastapi.testclient import TestClient

from otel_collector_proxy.main import create_app


@pytest_asyncio.fixture
async def app() -> AsyncGenerator[FastAPI]:
    app_ = create_app()
    yield app_


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            yield client


@pytest.fixture
def client_sync(app: FastAPI) -> Generator[TestClient]:
    with TestClient(app=app) as client:
        yield client
