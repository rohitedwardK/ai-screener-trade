"""Live Analysis tick orchestrator.

One `run_tick(db, now)` call:

  1. Read mode + config; short-circuit if not LIVE.
  2. Fetch quotes for the Nifty 50 + ^NSEI from Upstox (fallback to yfinance).
  3. Compute market regime from a rolling window of recent ^NSEI samples.
  4. Rank top-K movers across the 50.
  5. For each existing observation row:
       - if OBSERVING and a new sample is due (>= poll_interval_min since last):
            append; if window closes (sample_count >= observation_samples)
            run MFCS scorer, persist a `live_decisions` row, transition to
            COOLDOWN.
       - if COOLDOWN expired: transition to IDLE (we just delete the row -
            a fresh observation is created if/when the symbol returns to
            top movers).
  6. Promote eligible top-K movers (no active OBSERVING / COOLDOWN row) into
     fresh OBSERVING rows seeded with sample 0.
  7. Persist a `live_market_snapshots` row capturing regime + movers +
     counters.

All DB writes happen here. Pure scoring lives in `strategy`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..data import live_quotes, upstox_client
from ..models.live_analysis_orm import (
    LiveDecision,
    LiveMarketSnapshot,
    LiveObservation,
)
from ..models.orm import Candle, Snapshot, Stock
from . import config as live_config
from . import movers as movers_mod
from . import regime as regime_mod
from . import strategy as strategy_mod
from .observer import (
    STATE_COOLDOWN,
    STATE_OBSERVING,
    ObserverState,
    Sample,
    append_sample,
    cancel,
    mark_decided,
    maybe_release,
    start_observation,
)

log = logging.getLogger(__name__)


_NIFTY_INDEX_SYMBOL = "^NSEI"
_REGIME_WINDOW_SIZE = 8           # how many recent ^NSEI samples to feed regime
_AVG_VOLUME_WINDOW_DAYS = 20

# Per-day cache of (prev_close, avg_volume) to avoid hammering SQLite each tick.
_baseline_cache: Dict[str, Tuple[float, int]] = {}
_baseline_cache_date: Optional[datetime] = None


@dataclass
class TickResult:
    """Diagnostic summary returned by `run_tick`. Mirrors `LiveTickResult`
    in the paper-trading service."""
    processed_at: datetime
    mode: str
    market_open: bool
    symbols_priced: int
    regime: str
    top_movers_count: int
    observations_active: int
    observations_started: int
    decisions_emitted: int
    cooldowns_released: int
    note: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _refresh_baseline_cache(db: Session, when: datetime, symbols: List[str]) -> None:
    """Populate {symbol: (prev_close, avg_volume_20d)} once per UTC day.

    We pull the most recent 20 daily candles per symbol from the existing
    `candles` table populated by the daily refresh job. Computing this on
    every tick would be wasteful and would hammer SQLite; once per day is
    plenty since neither the prev close nor a 20-day SMA moves intraday.
    """
    global _baseline_cache_date
    today = when.date()
    if _baseline_cache_date == today and _baseline_cache:
        return

    _baseline_cache.clear()
    for sym in symbols:
        rows = list(db.scalars(
            select(Candle)
            .where(Candle.symbol == sym)
            .order_by(desc(Candle.date))
            .limit(_AVG_VOLUME_WINDOW_DAYS)
        ))
        if not rows:
            continue
        prev_close = float(rows[0].close)
        if len(rows) >= 2:
            avg_vol = int(sum(r.volume for r in rows[1:]) / max(len(rows) - 1, 1))
        else:
            avg_vol = int(rows[0].volume)
        _baseline_cache[sym] = (prev_close, avg_vol)
    _baseline_cache_date = today


def _latest_indicator_proxies(db: Session, symbol: str) -> Dict[str, Optional[float]]:
    """Pull the most recent daily snapshot indicators for a symbol.

    The 6-sample / 15-min window is too small to reliably compute classical
    indicators (RSI-14 needs 14+ bars; EMA-20 needs 20+). We use the latest
    DAILY snapshot's ema20 / rsi14 / atr as honest proxies. This matches the
    project's stated "research and decision-support" framing - not a tick-
    by-tick HFT signal.

    Returns a dict that may have None values; the strategy module handles
    them gracefully.
    """
    snap = db.scalar(
        select(Snapshot)
        .where(Snapshot.symbol == symbol)
        .order_by(desc(Snapshot.run_at))
        .limit(1)
    )
    if snap is None:
        return {"ema20": None, "rsi14": None, "atr": None}
    ind = snap.indicators_json or {}
    return {
        "ema20": float(ind["ema20"]) if ind.get("ema20") is not None else None,
        "rsi14": float(ind["rsi14"]) if ind.get("rsi14") is not None else None,
        "atr": float(snap.atr) if snap.atr is not None else None,
    }


def _fetch_quotes(symbols: List[str]) -> Tuple[Dict[str, float], Dict[str, int], Dict[str, float], str]:
    """Return (last_price, volume, prev_close_from_feed, source).

    Tries Upstox first; on empty response (no token / network error) falls
    back to yfinance LTPs (no volume, no prev_close).
    """
    if upstox_client.is_configured():
        quotes = upstox_client.fetch_quotes_batch(symbols)
        if quotes:
            return (
                {s: q.last_price for s, q in quotes.items()},
                {s: q.volume for s, q in quotes.items()},
                {s: q.close_prev for s, q in quotes.items() if q.close_prev > 0},
                "upstox",
            )

    # Fallback path: yfinance 1-min (~15 min delayed for NSE) gives us a
    # last price but no session volume. Movers ranking still works on
    # `pct_change` alone in this case.
    ltps = live_quotes.fetch_live_prices(symbols)
    return ltps, {}, {}, "yfinance"


def _window_vwap(samples: List[Sample]) -> Optional[float]:
    """Volume-weighted average price across the closed window."""
    if not samples:
        return None
    num = 0.0
    den = 0.0
    for s in samples:
        v = max(int(s.volume), 0)
        num += s.price * (v if v > 0 else 1)
        den += (v if v > 0 else 1)
    return num / den if den > 0 else None


def _window_rvol(observed_volume: int, avg_session_volume: int) -> float:
    """Approximate relative volume for the 15-min window.

    Scale the typical full-session volume to the same 15-min slice
    (15 / 375 trading minutes) and divide.
    """
    if avg_session_volume <= 0 or observed_volume <= 0:
        return 0.0
    expected = avg_session_volume * (15.0 / 375.0)
    return observed_volume / expected if expected > 0 else 0.0


def _last_window_volume(samples: List[Sample]) -> int:
    """Sum of the per-sample volume *deltas* (cumulative session vol -> per-3m)."""
    if len(samples) < 2:
        return 0
    total = 0
    for prev, cur in zip(samples[:-1], samples[1:]):
        delta = max(cur.volume - prev.volume, 0)
        total += delta
    return total


def _state_from_row(row: LiveObservation) -> ObserverState:
    """Hydrate the immutable observer state from a DB row."""
    samples: List[Sample] = []
    raw = row.samples or []
    for s in raw:
        try:
            samples.append(Sample(
                ts=datetime.fromisoformat(s["ts"]),
                price=float(s["price"]),
                volume=int(s.get("volume", 0)),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    cooldown_until = None
    if row.completed_at and row.status == STATE_COOLDOWN:
        # Engine never persists cooldown_until on the row; rebuild it from
        # completed_at + the (then-current) cooldown setting. The actual
        # cooldown_min is read by the caller and added before maybe_release.
        cooldown_until = row.completed_at
    return ObserverState(
        symbol=row.symbol,
        state=row.status,
        samples=samples,
        started_at=row.started_at,
        decided_at=row.completed_at,
        cooldown_until=cooldown_until,
    )


def _persist_state_to_row(row: LiveObservation, state: ObserverState) -> None:
    row.status = state.state
    row.sample_count = len(state.samples)
    row.samples = [
        {"ts": s.ts.isoformat(), "price": s.price, "volume": s.volume}
        for s in state.samples
    ]
    if state.decided_at:
        row.completed_at = state.decided_at


def _utc_now() -> datetime:
    """Naive UTC `datetime` consistent with the project's existing ORM defaults."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _build_nifty_window(db: Session, nifty_last: Optional[float]) -> List[float]:
    """Pull the last few persisted ^NSEI samples + the just-fetched LTP."""
    recent_snapshots = list(db.scalars(
        select(LiveMarketSnapshot)
        .order_by(desc(LiveMarketSnapshot.ts))
        .limit(_REGIME_WINDOW_SIZE - 1)
    ))
    window: List[float] = []
    # Oldest first so OLS sees a left-to-right time axis.
    for snap in reversed(recent_snapshots):
        if snap.nifty_last is not None:
            window.append(float(snap.nifty_last))
    if nifty_last is not None:
        window.append(float(nifty_last))
    return window


def _build_mover_inputs(
    nifty50_symbols: List[str],
    ltps: Dict[str, float],
    volumes: Dict[str, int],
    prev_closes_feed: Dict[str, float],
) -> List[movers_mod.MoverInput]:
    out: List[movers_mod.MoverInput] = []
    for sym in nifty50_symbols:
        last = ltps.get(sym)
        if not last or last <= 0:
            continue
        prev_close, avg_vol = _baseline_cache.get(sym, (0.0, 0))
        # Prefer the live feed's prev_close when present (more accurate on
        # corporate-action days) else fall back to the cached daily candle.
        prev_close = prev_closes_feed.get(sym, prev_close) or prev_close
        if prev_close <= 0:
            continue
        out.append(movers_mod.MoverInput(
            symbol=sym,
            last_price=last,
            prev_close=prev_close,
            volume=volumes.get(sym, 0),
            avg_volume=avg_vol,
        ))
    return out


def _close_window_and_emit_decision(
    db: Session,
    row: LiveObservation,
    new_state: ObserverState,
    *,
    cfg,
    when: datetime,
    regime: str,
) -> None:
    """Compute aggregates, run MFCS, persist a decision + cooldown transition."""
    proxies = _latest_indicator_proxies(db, row.symbol)
    _, avg_vol = _baseline_cache.get(row.symbol, (0.0, 0))
    observed_window_vol = _last_window_volume(new_state.samples)
    rvol = _window_rvol(observed_window_vol, avg_vol)
    vwap = _window_vwap(list(new_state.samples))

    # Use the closing 3-min "candle" approximated by (last two samples).
    if len(new_state.samples) >= 2:
        prev_s = new_state.samples[-2]
        cur_s = new_state.samples[-1]
        open_3m, close_3m = prev_s.price, cur_s.price
        high_3m, low_3m = max(prev_s.price, cur_s.price), min(prev_s.price, cur_s.price)
    else:
        open_3m = close_3m = high_3m = low_3m = float(new_state.samples[-1].price)

    obs_window = strategy_mod.ObservationWindow(
        symbol=row.symbol,
        samples=[s.price for s in new_state.samples],
        high_3m=high_3m, low_3m=low_3m, close_3m=close_3m, open_3m=open_3m,
        vwap=vwap, rvol=rvol,
        atr_3m=proxies.get("atr"),
        rsi_3m=proxies.get("rsi14"),
        ema20_3m=proxies.get("ema20"),
        regime=regime,
    )
    decision = strategy_mod.score_mfcs(obs_window, cfg)

    # Persist aggregates back onto the observation row for the UI.
    row.vwap = vwap
    row.rvol = rvol
    row.atr_3m = proxies.get("atr")
    row.rsi_3m = proxies.get("rsi14")
    row.ema20_3m = proxies.get("ema20")

    decided_state = mark_decided(new_state, decided_at=when, cooldown_min=cfg.cooldown_min)
    _persist_state_to_row(row, decided_state)

    db.add(LiveDecision(
        observation_id=row.id,
        symbol=row.symbol,
        ts=when,
        direction=decision.direction,
        confidence=float(decision.confidence),
        long_raw=float(decision.long_raw),
        short_raw=float(decision.short_raw),
        invalidation=decision.invalidation,
        regime=decision.regime,
        factors=decision.factors,
    ))


def _walk_observations(
    db: Session,
    rows: List[LiveObservation],
    *,
    cfg,
    when: datetime,
    ltps: Dict[str, float],
    volumes: Dict[str, int],
    regime: str,
    min_step_seconds: float,
) -> Dict[str, int]:
    """Advance every existing observation row. Returns counter dict."""
    counters = {"cooldowns_released": 0, "decisions_emitted": 0, "observations_active": 0}
    for row in rows:
        state = _state_from_row(row)

        if state.state == STATE_COOLDOWN:
            if state.cooldown_until is not None:
                full_until = state.cooldown_until + timedelta(minutes=cfg.cooldown_min)
                released = ObserverState(
                    symbol=state.symbol, state=state.state,
                    samples=state.samples, started_at=state.started_at,
                    decided_at=state.decided_at, cooldown_until=full_until,
                )
                if maybe_release(released, now=when).state != STATE_COOLDOWN:
                    db.delete(row)
                    counters["cooldowns_released"] += 1
            continue

        last_price = ltps.get(row.symbol)
        if last_price is None or last_price <= 0:
            new_state = cancel(state, now=when, cooldown_min=cfg.cooldown_min)
            _persist_state_to_row(row, new_state)
            row.note = "cancelled: no live price"
            continue

        sample = Sample(
            ts=when, price=float(last_price),
            volume=int(volumes.get(row.symbol, 0)),
        )
        new_state, closed = append_sample(
            state, sample,
            target_samples=cfg.observation_samples,
            min_step_seconds=min_step_seconds,
        )
        counters["observations_active"] += 1

        if not closed:
            _persist_state_to_row(row, new_state)
            continue

        _close_window_and_emit_decision(
            db, row, new_state, cfg=cfg, when=when, regime=regime,
        )
        counters["decisions_emitted"] += 1
    return counters


def _promote_movers(
    db: Session,
    top_movers: List[movers_mod.Mover],
    rows_by_symbol: Dict[str, LiveObservation],
    *,
    when: datetime,
    ltps: Dict[str, float],
    volumes: Dict[str, int],
) -> int:
    """Seed fresh OBSERVING rows for top movers not already being tracked."""
    started = 0
    for mover in top_movers:
        if mover.symbol in rows_by_symbol:
            continue
        last_price = ltps.get(mover.symbol)
        if not last_price or last_price <= 0:
            continue
        first_sample = Sample(
            ts=when,
            price=float(last_price),
            volume=int(volumes.get(mover.symbol, 0)),
        )
        seed_state = start_observation(
            ObserverState(symbol=mover.symbol),
            now=when,
            first_sample=first_sample,
        )
        db.add(LiveObservation(
            symbol=mover.symbol,
            started_at=when,
            status=seed_state.state,
            sample_count=len(seed_state.samples),
            samples=[
                {"ts": s.ts.isoformat(), "price": s.price, "volume": s.volume}
                for s in seed_state.samples
            ],
        ))
        started += 1
    return started


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run_tick(db: Session, *, now: Optional[datetime] = None) -> TickResult:
    """Execute one Live Analysis tick. Idempotent and exception-safe at the
    top level - the scheduler caller wraps it again in case the DB itself
    explodes.
    """
    when = now or _utc_now()
    cfg = live_config.snapshot(db)

    if cfg.mode != live_config.MODE_LIVE:
        return TickResult(
            processed_at=when, mode=cfg.mode, market_open=False,
            symbols_priced=0, regime="UNKNOWN", top_movers_count=0,
            observations_active=0, observations_started=0,
            decisions_emitted=0, cooldowns_released=0,
            note="mode != LIVE",
        )

    nifty50_symbols = [s.symbol for s in db.scalars(select(Stock).order_by(Stock.symbol))]
    if not nifty50_symbols:
        return TickResult(
            processed_at=when, mode=cfg.mode, market_open=False,
            symbols_priced=0, regime="UNKNOWN", top_movers_count=0,
            observations_active=0, observations_started=0,
            decisions_emitted=0, cooldowns_released=0,
            note="no stocks in universe",
        )

    fetch_symbols = list(nifty50_symbols) + [_NIFTY_INDEX_SYMBOL]
    ltps, volumes, prev_closes_feed, source = _fetch_quotes(fetch_symbols)
    nifty_last = ltps.get(_NIFTY_INDEX_SYMBOL)

    _refresh_baseline_cache(db, when, nifty50_symbols)

    nifty_window = _build_nifty_window(db, nifty_last)
    regime_result = regime_mod.classify_market(nifty_window, cfg=cfg)

    mover_inputs = _build_mover_inputs(nifty50_symbols, ltps, volumes, prev_closes_feed)
    top_movers = movers_mod.rank_top_k(mover_inputs, k=cfg.top_k_movers)

    rows = list(db.scalars(
        select(LiveObservation)
        .where(LiveObservation.status.in_([STATE_OBSERVING, STATE_COOLDOWN]))
    ))
    rows_by_symbol: Dict[str, LiveObservation] = {r.symbol: r for r in rows}

    min_step_seconds = max(cfg.poll_interval_min * 60 - 30, 60)
    counters = _walk_observations(
        db, rows, cfg=cfg, when=when, ltps=ltps, volumes=volumes,
        regime=regime_result.regime, min_step_seconds=min_step_seconds,
    )

    started = _promote_movers(
        db, top_movers, rows_by_symbol,
        when=when, ltps=ltps, volumes=volumes,
    )
    counters["observations_active"] += started

    db.add(LiveMarketSnapshot(
        ts=when,
        regime=regime_result.regime,
        nifty_last=regime_result.last,
        nifty_z=regime_result.z,
        nifty_slope=regime_result.slope,
        nifty_vwap_dev=regime_result.vwap_dev,
        top_movers=[
            {
                "symbol": m.symbol, "last": m.last_price,
                "pct_change": m.pct_change, "rvol": m.rvol,
                "rank": m.rank, "score": m.score,
            }
            for m in top_movers
        ],
        counters={
            "priced": len(ltps),
            "source": source,
            "observations_active": counters["observations_active"],
            "observations_started": started,
            "decisions_emitted": counters["decisions_emitted"],
            "cooldowns_released": counters["cooldowns_released"],
        },
    ))
    db.commit()

    return TickResult(
        processed_at=when,
        mode=cfg.mode,
        market_open=True,
        symbols_priced=len(ltps),
        regime=regime_result.regime,
        top_movers_count=len(top_movers),
        observations_active=counters["observations_active"],
        observations_started=started,
        decisions_emitted=counters["decisions_emitted"],
        cooldowns_released=counters["cooldowns_released"],
        note=f"source={source}",
    )


__all__ = ["TickResult", "run_tick"]
