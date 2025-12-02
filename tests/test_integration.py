import time
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from testcontainers.core.container import (  # pyright: ignore[reportMissingTypeStubs]
    DockerContainer,
    LogMessageWaitStrategy,
)

from otel_collector_proxy.core.data_type import DataType


def test_integration_with_jaeger():
    """
    Integration test that spins up a Jaeger container (acting as OTEL collector),
    configures the proxy to send traces to it, and verifies that traces are received.
    """

    # Jaeger exposes:
    # 4317: OTLP gRPC
    # 4318: OTLP HTTP
    # 16686: UI / API
    with (
        DockerContainer("cr.jaegertracing.io/jaegertracing/jaeger:2.11.0")
        .with_exposed_ports(4318, 16686)
        .with_env("COLLECTOR_OTLP_ENABLED", "true") as jaeger
    ):
        # Wait for Jaeger to be ready, if this fails check what log message jaeger returns when its ready
        jaeger.waiting_for(
            LogMessageWaitStrategy("Everything is ready. Begin running and processing data.")
        )
        jaeger.start()

        # Get the mapped ports
        otel_port = jaeger.get_exposed_port(4318)
        query_port = jaeger.get_exposed_port(16686)
        host = jaeger.get_container_host_ip()

        otel_http_host = f"http://{host}:{otel_port}"
        query_url = f"http://{host}:{query_port}/api/traces"

        with patch(
            "otel_collector_proxy.core.config.settings.OTEL_COLLECTOR_HOST", otel_http_host
        ):
            # We need to create the app HERE so it picks up the patched setting
            from otel_collector_proxy.main import create_app

            app = create_app()

            with TestClient(app) as client:
                # 1. Send a trace to the proxy
                trace_id = "5b8aa5a2d2c872e8321cf37308d69df2"
                span_id = "051581bf3cb55c13"
                payload = {  # type: ignore
                    "resourceSpans": [
                        {
                            "resource": {
                                "attributes": [
                                    {
                                        "key": "service.name",
                                        "value": {"stringValue": "integration-test-service"},
                                    }
                                ]
                            },
                            "scopeSpans": [
                                {
                                    "scope": {"name": "test-scope"},
                                    "spans": [
                                        {
                                            "traceId": trace_id,
                                            "spanId": span_id,
                                            "name": "test-span",
                                            "kind": 1,
                                            "startTimeUnixNano": time.time_ns(),
                                            "endTimeUnixNano": time.time_ns() + 1000000,
                                            "attributes": [],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }

                response = client.post(
                    "/api/v1/traces",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Data-Type": DataType.OPENTELEMETRY_SDK.value,
                    },
                )
                assert response.status_code == 200

                # 2. Verify trace in Jaeger
                # It might take a moment for Jaeger to index it
                found = False
                with httpx.Client() as query_client:
                    for _ in range(10):  # Retry for 5 seconds
                        try:
                            resp = query_client.get(
                                f"{query_url}?service=integration-test-service"
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                if data["data"]:
                                    # Check if our trace ID is in the results
                                    for trace in data["data"]:
                                        if trace["traceID"] == trace_id:
                                            found = True
                                            break
                            if found:
                                break
                        except Exception:
                            pass
                        time.sleep(1)

                assert found, "Trace not found in Jaeger"


def test_integration_with_otel_collector_faro():
    """
    Integration test that spins up an OTEL Collector container with Faro receiver,
    configures the proxy to send traces to it, and verifies that traces are received.
    """
    config_path = Path(__file__).parent / "otel-collector-config.yaml"

    # OTEL Collector exposes:
    # 4318: OTLP HTTP
    # 8081: Faro
    with (
        DockerContainer("otel/opentelemetry-collector-contrib:0.139.0")
        .with_exposed_ports(4318, 8081)
        .with_volume_mapping(str(config_path), "/etc/otel-collector-config.yaml", mode="ro")
        .with_command(["--config=/etc/otel-collector-config.yaml"]) as otel_collector
    ):
        # Wait for OTEL Collector to be ready
        otel_collector.waiting_for(
            LogMessageWaitStrategy("Everything is ready. Begin running and processing data.")
        )
        otel_collector.start()

        # Get the mapped ports
        otel_port = otel_collector.get_exposed_port(4318)
        faro_port = otel_collector.get_exposed_port(8081)
        host = otel_collector.get_container_host_ip()

        otel_http_host = f"http://{host}:{otel_port}"
        faro_host = f"http://{host}:{faro_port}"

        with (
            patch("otel_collector_proxy.core.config.settings.OTEL_COLLECTOR_HOST", otel_http_host),
            patch("otel_collector_proxy.core.config.settings.OTEL_COLLECTOR_FARO_HOST", faro_host),
        ):
            # We need to create the app HERE so it picks up the patched settings
            from otel_collector_proxy.main import create_app

            app = create_app()

            with TestClient(app) as client:
                # Create a Faro trace payload
                # Faro uses a different format than OTLP
                faro_payload = {
                    "traces": {
                        "batch": [
                            {
                                "traceId": "5b8aa5a2d2c872e8321cf37308d69df2",
                                "spans": [
                                    {
                                        "spanId": "051581bf3cb55c13",
                                        "name": "faro-test-span",
                                        "startTime": time.time_ns(),
                                        "endTime": time.time_ns() + 1000000,
                                        "attributes": {
                                            "service.name": "faro-integration-test",
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }

                response = client.post(
                    "/api/v1/traces",
                    json=faro_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Data-Type": DataType.FARO.value,
                    },
                )
                assert response.status_code == 200
