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

    # CSV cache directories. Defaults match the historical layout (relative to
    # the backend working directory) so local dev keeps working unchanged. In
    # cloud deploys point these at a persistent volume, e.g. /data/ohlcv.
    STOCK_DATA_DIR: str = "data/ohlcv"
    INDEX_DATA_DIR: str = "data/ohlcv-indices"
    INDEX_INTRADAY_DATA_DIR: str = "data/ohlcv-indices-intraday"

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
    # Includes capacitor://localhost (Android Capacitor APK) and
    # http(s)://localhost (iOS Capacitor / Capacitor live reload) so the
    # mobile shell can hit the API without a per-deploy override.
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "capacitor://localhost,http://localhost,https://localhost"
    )

    # Live Analysis Mode (Upstox-backed real-time)
    UPSTOX_API_KEY: str = ""
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_BASE_URL: str = "https://api.upstox.com/v2"
    LIVE_ANALYSIS_ENABLED: bool = True
    LIVE_ANALYSIS_POLL_MIN: int = 3
    LIVE_ANALYSIS_OBS_SAMPLES: int = 6
    LIVE_ANALYSIS_TOP_K: int = 8
    LIVE_ANALYSIS_COOLDOWN_MIN: int = 30

    # Agentic layer (CrewAI head agent + worker agents on local Ollama).
    # AGENTIC_FAST_TICK_SEC is approximate; APScheduler grains at 1 minute so
    # the fast monitor effectively runs once per minute and short-circuits
    # outside NSE hours.
    AGENTIC_ENABLED: bool = True
    AGENTIC_DEEP_CYCLE_MIN: int = 15
    AGENTIC_FAST_TICK_SEC: int = 60
    AGENTIC_BOOT_CYCLE: bool = True
    # CrewAI 1.14+ recommends the OpenAI-compatible path for Ollama so the
    # LiteLLM transitive dep can be skipped. The model name is whatever
    # `ollama list` shows; the base URL hits Ollama's /v1 OpenAI shim.
    AGENTIC_LLM_MODEL: str = "openai/llama3.2:latest"
    AGENTIC_LLM_BASE_URL: str = "http://localhost:11434/v1"
    AGENTIC_LLM_API_KEY: str = "ollama"
    AGENTIC_LLM_TIMEOUT_SEC: int = 240
    # Informant agent lookahead window for upcoming events. Default 5 days
    # matches the original product brief ("today + within 5 days"). Bump if
    # you want a longer earnings preview; events past this horizon are
    # silently dropped.
    AGENTIC_INFORMANT_DAYS_AHEAD: int = 5
    # India VIX bands. Anything below HIGH is "NORMAL"; >=HIGH and <PANIC is
    # "ELEVATED"; >=PANIC is "PANIC". Values informed by NSE long-run
    # distribution (median ~13, 75th pctile ~17, crisis spikes >25).
    INDIA_VIX_HIGH: float = 18.0
    INDIA_VIX_PANIC: float = 25.0
    # Comma-separated RSS feed URLs consumed by MarketContextAgent.
    NEWS_RSS_FEEDS: str = (
        "https://www.moneycontrol.com/rss/marketreports.xml,"
        "https://www.moneycontrol.com/rss/business.xml,"
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
    )

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def news_rss_feed_list(self) -> List[str]:
        return [u.strip() for u in self.NEWS_RSS_FEEDS.split(",") if u.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
