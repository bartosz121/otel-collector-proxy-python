from enum import StrEnum

from pydantic_settings import BaseSettings


class Environment(StrEnum):
    TESTING = "TESTING"
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"

    @property
    def is_testing(self) -> bool:
        return self == Environment.TESTING

    @property
    def is_development(self) -> bool:
        return self == Environment.DEVELOPMENT

    @property
    def is_staging(self) -> bool:
        return self == Environment.STAGING

    @property
    def is_qa(self) -> bool:
        return self in {
            Environment.TESTING,
            Environment.DEVELOPMENT,
            Environment.STAGING,
        }

    @property
    def is_production(self) -> bool:
        return self == Environment.PRODUCTION


class Settings(BaseSettings):
    ENVIRONMENT: Environment = Environment.PRODUCTION
    LOG_LEVEL: str = "DEBUG"
    ENABLED_LOGGERS: list[str] = ["granian", "httpx"]

    OTEL_COLLECTOR_HTTP_HOST: str = "http://localhost:4318"
    OTEL_COLLECTOR_HTTP_ENDPOINT: str = "/v1/traces"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    PROMETHEUS_MULTIPROC_DIR: str | None = None
    MAX_BODY_SIZE: int = 1024 * 1024 * 5  # 5 MB
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60


settings = Settings()
