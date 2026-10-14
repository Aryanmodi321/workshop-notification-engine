from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://workshop:workshop@localhost:5432/workshops"
    notification_service_url: str = "http://localhost:8001"
    worker_poll_seconds: float = 1.0
    worker_max_attempts: int = 8
    worker_lease_seconds: int = 60
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 300.0
    http_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
