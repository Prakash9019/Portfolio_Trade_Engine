from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Kalpi Portfolio Execution Engine"
    environment: str = "local"
    live_trading_enabled: bool = False
    retry_attempts: int = Field(default=3, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=0.0, ge=0.0, le=5.0)
    idempotency_wait_seconds: float = Field(default=30.0, gt=0.0, le=120.0)
    log_level: str = "INFO"
    mock_fail_symbols: str = ""
    model_config = SettingsConfigDict(env_file=".env", env_prefix="KALPI_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
