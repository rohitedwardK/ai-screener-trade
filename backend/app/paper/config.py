"""Paper-trading bot configuration: single-row pattern with spec defaults."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.paper_orm import PaperBotConfig

# --- Spec defaults ---
DEFAULT_VIRTUAL_CAPITAL = 100_000.0
DEFAULT_MAX_TRADES_PER_DAY = 5
DEFAULT_MAX_OPEN_POSITIONS = 5
DEFAULT_MAX_RISK_PER_TRADE_PERCENT = 0.5
DEFAULT_MAX_DAILY_LOSS_PERCENT = 2.0
DEFAULT_MIN_SCORE = 75.0
DEFAULT_MIN_RISK_REWARD = 2.0
DEFAULT_PARTIAL_EXIT_PERCENT = 50.0
DEFAULT_TRAILING_STOP_ENABLED = True
DEFAULT_SAME_CANDLE_POLICY = "conservative"  # conservative | optimistic | ohlc_approx
ALLOWED_SAME_CANDLE_POLICIES = {"conservative", "optimistic", "ohlc_approx"}
DEFAULT_LIVE_TRADING_ENABLED = False
DEFAULT_LIVE_POLL_INTERVAL_SECONDS = 60
MIN_LIVE_POLL_INTERVAL_SECONDS = 30  # lower bound to keep yfinance happy


@dataclass(frozen=True)
class PaperConfigSnapshot:
    """Immutable in-memory snapshot of the bot config (avoid DB ops in hot loops)."""
    virtual_capital: float = DEFAULT_VIRTUAL_CAPITAL
    max_trades_per_day: int = DEFAULT_MAX_TRADES_PER_DAY
    max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS
    max_risk_per_trade_percent: float = DEFAULT_MAX_RISK_PER_TRADE_PERCENT
    max_daily_loss_percent: float = DEFAULT_MAX_DAILY_LOSS_PERCENT
    min_score: float = DEFAULT_MIN_SCORE
    min_risk_reward: float = DEFAULT_MIN_RISK_REWARD
    partial_exit_percent: float = DEFAULT_PARTIAL_EXIT_PERCENT
    trailing_stop_enabled: bool = DEFAULT_TRAILING_STOP_ENABLED
    same_candle_policy: str = DEFAULT_SAME_CANDLE_POLICY
    live_trading_enabled: bool = DEFAULT_LIVE_TRADING_ENABLED
    live_poll_interval_seconds: int = DEFAULT_LIVE_POLL_INTERVAL_SECONDS


def get_or_create(db: Session) -> PaperBotConfig:
    """Return the singleton config row, creating it with defaults on first call."""
    cfg = db.scalar(select(PaperBotConfig).order_by(PaperBotConfig.id.asc()).limit(1))
    if cfg is not None:
        return cfg
    cfg = PaperBotConfig()
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def update(db: Session, **patch) -> PaperBotConfig:
    cfg = get_or_create(db)
    if "same_candle_policy" in patch and patch["same_candle_policy"] is not None:
        if patch["same_candle_policy"] not in ALLOWED_SAME_CANDLE_POLICIES:
            raise ValueError(
                f"same_candle_policy must be one of {sorted(ALLOWED_SAME_CANDLE_POLICIES)}"
            )
    if "live_poll_interval_seconds" in patch and patch["live_poll_interval_seconds"] is not None:
        if int(patch["live_poll_interval_seconds"]) < MIN_LIVE_POLL_INTERVAL_SECONDS:
            raise ValueError(
                f"live_poll_interval_seconds must be >= {MIN_LIVE_POLL_INTERVAL_SECONDS}"
            )
    for k, v in patch.items():
        if v is not None and hasattr(cfg, k):
            setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return cfg


def snapshot(db: Session) -> PaperConfigSnapshot:
    cfg = get_or_create(db)
    return PaperConfigSnapshot(
        virtual_capital=cfg.virtual_capital,
        max_trades_per_day=cfg.max_trades_per_day,
        max_open_positions=cfg.max_open_positions,
        max_risk_per_trade_percent=cfg.max_risk_per_trade_percent,
        max_daily_loss_percent=cfg.max_daily_loss_percent,
        min_score=cfg.min_score,
        min_risk_reward=cfg.min_risk_reward,
        partial_exit_percent=cfg.partial_exit_percent,
        trailing_stop_enabled=cfg.trailing_stop_enabled,
        same_candle_policy=cfg.same_candle_policy,
        live_trading_enabled=bool(getattr(cfg, "live_trading_enabled", False)),
        live_poll_interval_seconds=int(getattr(cfg, "live_poll_interval_seconds", DEFAULT_LIVE_POLL_INTERVAL_SECONDS)),
    )
