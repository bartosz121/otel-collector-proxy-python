from unittest.mock import patch

import httpx
from fastapi import status
from respx import MockRouter

from otel_collector_proxy.core.config import Environment


async def test_traces_endpoint_success(
    client: httpx.AsyncClient,
    respx_mock: MockRouter,
):
    respx_mock.post("http://localhost:4318/v1/traces").mock(
        return_value=httpx.Response(status.HTTP_200_OK, json={"status": "ok"})
    )

    response = await client.post(
        "/api/v1/traces",
        json={"resourceSpans": []},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


async def test_traces_endpoint_failure(client: httpx.AsyncClient, respx_mock: MockRouter):
    respx_mock.post("http://localhost:4318/v1/traces").mock(
        return_value=httpx.Response(status.HTTP_500_INTERNAL_SERVER_ERROR)
    )

    response = await client.post(
        "/api/v1/traces",
        json={"resourceSpans": []},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


async def test_traces_endpoint_connection_error(client: httpx.AsyncClient, respx_mock: MockRouter):
    respx_mock.post("http://localhost:4318/v1/traces").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    response = await client.post(
        "/api/v1/traces",
        json={"resourceSpans": []},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == status.HTTP_502_BAD_GATEWAY


async def test_traces_endpoint_missing_content_type(client: httpx.AsyncClient):
    response = await client.post(
        "/api/v1/traces",
        content=b"{}",
        # No Content-Type header
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.content == b"Missing Content-Type header"


async def test_traces_endpoint_payload_too_large(client: httpx.AsyncClient):
    # Default limit is 5MB
    large_payload = b"a" * (1024 * 1024 * 5 + 1)

    response = await client.post(
        "/api/v1/traces",
        content=large_payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert response.content == b"Payload too large"


async def test_development_environment_normal_response(client: httpx.AsyncClient):
    """
    In DEVELOPMENT, responses should return their original status code.
    """
    with patch("otel_collector_proxy.core.config.settings.ENVIRONMENT", Environment.DEVELOPMENT):
        # Sending a request without Content-Type should return 400
        response = await client.post("/api/v1/traces", content=b"{}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.content == b"Missing Content-Type header"


async def test_production_environment_secure_response(client: httpx.AsyncClient):
    """
    In PRODUCTION, all error responses should be masked as 204.
    """
    with patch("otel_collector_proxy.core.config.settings.ENVIRONMENT", Environment.PRODUCTION):
        # 1. Missing Content-Type (originally 400) -> 204
        response = await client.post("/api/v1/traces", content=b"{}")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""

        # 2. Payload too large (originally 413) -> 204
        with patch("otel_collector_proxy.core.config.settings.MAX_BODY_SIZE", 10):
            response = await client.post(
                "/api/v1/traces",
                content=b"A" * 20,
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT
            assert response.content == b""


async def test_production_environment_success_response(client: httpx.AsyncClient):
    """
    In PRODUCTION, successful responses (200) should be masked as 204.
    And the request should be forwarded in the background.
    """
    with patch("otel_collector_proxy.core.config.settings.ENVIRONMENT", Environment.PRODUCTION):
        response = await client.post(
            "/api/v1/traces",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )

        # It should be 204
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""
        assert "x-m-r" in response.headers.keys()
        assert response.headers.get("x-m-r") == "1"


async def test_development_environment_success_response(client: httpx.AsyncClient):
    """
    In DEVELOPMENT, successful responses should be returned as is.
    """
    with patch("otel_collector_proxy.core.config.settings.ENVIRONMENT", Environment.DEVELOPMENT):
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.content = b"Created"
            mock_post.return_value.headers = {"content-type": "text/plain"}

            response = await client.post(
                "/api/v1/traces",
                content=b"{}",
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 201
            assert response.content == b"Created"
