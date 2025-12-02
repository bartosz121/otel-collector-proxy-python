from enum import Enum


class DataType(str, Enum):
    OPENTELEMETRY_SDK = "opentelemetry-sdk"
    FARO = "faro"
