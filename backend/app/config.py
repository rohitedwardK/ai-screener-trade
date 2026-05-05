"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DB_URL: str = "sqlite:///./screener.db"

    # Data fetch
    HISTORY_PERIOD: str = "5y"
    INTERVAL: str = "1d"

    # Scheduler
    REFRESH_CRON_HOUR: int = 18
    REFRESH_CRON_MINUTE: int = 30
    ENABLE_SCHEDULER: bool = True

    # LLM provider
    LLM_PROVIDER: str = "template"  # template | ollama | openai
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1"
    # CPU inference of a 3B+ model can easily exceed 60s for a multi-paragraph
    # answer; default 180s avoids spurious template fallbacks on local setups.
    OLLAMA_TIMEOUT_SECONDS: float = 180.0
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT_SECONDS: float = 60.0

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Live Analysis Mode (Upstox-backed real-time)
    UPSTOX_API_KEY: str = ""
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_BASE_URL: str = "https://api.upstox.com/v2"
    LIVE_ANALYSIS_ENABLED: bool = True
    LIVE_ANALYSIS_POLL_MIN: int = 3
    LIVE_ANALYSIS_OBS_SAMPLES: int = 6
    LIVE_ANALYSIS_TOP_K: int = 8
    LIVE_ANALYSIS_COOLDOWN_MIN: int = 30

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
