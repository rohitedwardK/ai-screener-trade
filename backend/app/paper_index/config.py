"""Paper-index bot configuration: single-row pattern with sensible defaults."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.paper_index_orm import PaperIndexBotConfig

DEFAULT_VIRTUAL_CAPITAL = 100_000.0
DEFAULT_MAX_TRADES_PER_DAY = 5
DEFAULT_MAX_OPEN_POSITIONS = 3
DEFAULT_MAX_RISK_PER_TRADE_PERCENT = 1.0
DEFAULT_MAX_DAILY_LOSS_PERCENT = 3.0
DEFAULT_MIN_SCORE = 70.0
DEFAULT_MIN_RISK_REWARD = 1.5
DEFAULT_PARTIAL_EXIT_PERCENT = 50.0
DEFAULT_TRAILING_STOP_ENABLED = True
DEFAULT_SAME_CANDLE_POLICY = "conservative"
DEFAULT_OPTION_MONEYNESS = "ATM"
DEFAULT_OPTION_DELTA_ESTIMATE = 0.5
DEFAULT_USE_OPTION_CHAIN_BIAS = True
DEFAULT_INTRADAY_POLL_SECONDS = 60
DEFAULT_INTRADAY_SIGNAL_MINUTES = 5
# Index-options weekly lifecycle is ~5 trading days, so the bot intentionally
# trades on a tighter horizon than the stock layer.
DEFAULT_ENTRY_ORDER_EXPIRY_DAYS = 1
DEFAULT_MAX_HOLDING_DAYS = 3
DEFAULT_INTRADAY_HORIZON_DAYS = 1
DEFAULT_LIVE_TRADING_ENABLED = False
DEFAULT_LIVE_POLL_INTERVAL_SECONDS = 60

ALLOWED_SAME_CANDLE_POLICIES = {"conservative", "optimistic", "ohlc_approx"}
ALLOWED_MONEYNESS = {"ATM", "ITM1", "OTM1"}


@dataclass(frozen=True)
class PaperIndexConfigSnapshot:
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
    option_moneyness: str = DEFAULT_OPTION_MONEYNESS
    option_delta_estimate: float = DEFAULT_OPTION_DELTA_ESTIMATE
    use_option_chain_bias: bool = DEFAULT_USE_OPTION_CHAIN_BIAS
    intraday_poll_seconds: int = DEFAULT_INTRADAY_POLL_SECONDS
    intraday_signal_minutes: int = DEFAULT_INTRADAY_SIGNAL_MINUTES
    entry_order_expiry_days: int = DEFAULT_ENTRY_ORDER_EXPIRY_DAYS
    max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS
    intraday_horizon_days: int = DEFAULT_INTRADAY_HORIZON_DAYS
    live_trading_enabled: bool = DEFAULT_LIVE_TRADING_ENABLED
    live_poll_interval_seconds: int = DEFAULT_LIVE_POLL_INTERVAL_SECONDS


def get_or_create(db: Session) -> PaperIndexBotConfig:
    cfg = db.scalar(select(PaperIndexBotConfig).order_by(PaperIndexBotConfig.id.asc()).limit(1))
    if cfg is not None:
        return cfg
    cfg = PaperIndexBotConfig()
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def update(db: Session, **patch) -> PaperIndexBotConfig:
    cfg = get_or_create(db)
    if "same_candle_policy" in patch and patch["same_candle_policy"] is not None:
        if patch["same_candle_policy"] not in ALLOWED_SAME_CANDLE_POLICIES:
            raise ValueError(
                f"same_candle_policy must be one of {sorted(ALLOWED_SAME_CANDLE_POLICIES)}"
            )
    if "option_moneyness" in patch and patch["option_moneyness"] is not None:
        if patch["option_moneyness"] not in ALLOWED_MONEYNESS:
            raise ValueError(f"option_moneyness must be one of {sorted(ALLOWED_MONEYNESS)}")
    for k, v in patch.items():
        if v is not None and hasattr(cfg, k):
            setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return cfg


def snapshot(db: Session) -> PaperIndexConfigSnapshot:
    cfg = get_or_create(db)
    return PaperIndexConfigSnapshot(
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
        option_moneyness=cfg.option_moneyness,
        option_delta_estimate=cfg.option_delta_estimate,
        use_option_chain_bias=cfg.use_option_chain_bias,
        intraday_poll_seconds=cfg.intraday_poll_seconds,
        intraday_signal_minutes=cfg.intraday_signal_minutes,
        entry_order_expiry_days=cfg.entry_order_expiry_days,
        max_holding_days=cfg.max_holding_days,
        intraday_horizon_days=cfg.intraday_horizon_days,
        live_trading_enabled=cfg.live_trading_enabled,
        live_poll_interval_seconds=cfg.live_poll_interval_seconds,
    )
