"""Live Market service configuration.

Independent from the parent app's `Settings` so deployments can run either
service standalone. Reads the same `UPSTOX_*` env vars the parent uses, so
operators rotate one token per day for both processes.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# We deliberately load the parent app's backend/.env first (operator keeps the
# rotated UPSTOX_* token there, shared with the parent screener) and let an
# optional live-market/backend/.env override locally. pydantic-settings honors
# the tuple order with later entries taking precedence.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PARENT_ENV = _REPO_ROOT / "backend" / ".env"
_LOCAL_ENV = Path(".env")
_ENV_FILES: tuple[str, ...] = tuple(
    str(p) for p in (_PARENT_ENV, _LOCAL_ENV) if p.exists()
) or (str(_LOCAL_ENV),)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database (separate file, never shared with the parent screener.db).
    DB_URL: str = "sqlite:///./data/live_market.db"

    # Upstox v2 - same env vars as the parent app for operator simplicity.
    UPSTOX_API_KEY: str = ""
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_BASE_URL: str = "https://api.upstox.com/v2"

    # Daily OHLCV CSV cache directory shared with the parent app. Defaults
    # to the parent layout (../../backend/data/ohlcv-indices) so a local
    # dev clone "just works"; cloud deploys point this at a persistent
    # volume.
    INDEX_DATA_DIR: str = "../../backend/data/ohlcv-indices"

    # Scheduler / poll cadence
    LIVE_MARKET_ENABLED: bool = True
    LIVE_MARKET_POLL_MIN: int = 1            # 1-minute REST cadence
    LIVE_MARKET_BAR_HISTORY: int = 375       # one full NSE session of 1-min bars
    LIVE_MARKET_HYDRATE_ON_BOOT: bool = True

    # Scalp / swing engine knobs
    SCALP_TARGET_SPOT_PCT: float = 0.005     # 0.5% spot move target
    SCALP_STOP_SPOT_PCT: float = 0.003       # 0.3% spot move stop
    SCALP_EXPIRY_MIN: int = 20               # auto-EXPIRED if not entered
    SWING_TARGET_ATR_MULT: float = 2.0
    SWING_STOP_ATR_MULT: float = 1.0
    SWING_T1_ATR_MULT: float = 1.2
    SWING_HORIZON_DAYS: int = 3

    # Regime classifier knobs (see analysis/market_regime.py)
    REGIME_TREND_ADX_MIN: float = 22.0
    REGIME_RANGE_ADX_MAX: float = 20.0
    REGIME_TREND_EMA_SPREAD_PCT: float = 0.0010   # 0.10%
    REGIME_RANGE_BB_SQUEEZE: float = 0.6          # current BB width / 20-bar avg

    # CORS
    CORS_ORIGINS: str = (
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
