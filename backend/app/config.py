"""应用配置。"""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用运行时配置，来自环境变量或 `.env` 文件。"""

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "12345678"
    PG_DSN: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/xiaoc_assistant"
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "http://127.0.0.1:5500,http://localhost:5500"
    REQUEST_TIMEOUT_SECONDS: float = 10.0
    REQUEST_RETRY_COUNT: int = 3
    REQUEST_RETRY_BACKOFF: float = 0.25

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""

    QWEATHER_HOST: str | None = None
    QWEATHER_API_KEY: str | None = None
    AMAP_API_KEY: str | None = None

    model_config = {
        "env_file": str(Path(__file__).resolve().parents[1] / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
