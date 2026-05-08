"""Tool surface for the agentic layer.

Every tool is a thin wrapper around an existing deterministic service so the
agent layer cannot break price/signal math. Each worker agent calls these
`*_impl` functions directly; the head agent uses their structured outputs
to ground its markdown synthesis (the only step that touches the LLM).

Public surface:

    refresh_stocks_impl(force_full=False) -> dict
    refresh_indices_intraday_impl()       -> dict
    cache_status_impl()                   -> dict
    rank_methods_impl(top_k=15)           -> dict
    consensus_picks_impl(top_k=10, min_votes=2) -> list[dict]
    screener_signals_impl(category=None, min_score=0) -> list[dict]
    vix_level_impl()                      -> dict
    market_regime_impl()                  -> dict
    news_headlines_impl(limit=10)         -> list[dict]
    sector_rotation_impl()                -> list[dict]
    live_movers_impl(k=15)                -> dict
    refresh_verification_impl()           -> dict
    check_invalidations_impl(prev_top)    -> list[dict]

Error handling: each impl catches broad `Exception` and returns a dict
with `"error"` key set. The orchestrator surfaces that into the
`AgentRun.worker_statuses_json` so a single failing tool degrades the
worker to PARTIAL but never kills the whole crew.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import desc, select

from ..analysis import ml_gbm, ml_lstm, ml_rf
from ..api.method_analysis import (
    _baseline_prev_close_avg_vol,
    _fetch_quotes_nifty50,
    _run_rule_based,
)
from ..core import live_verification as live_verif_core
from ..core.index_pipeline import refresh_intraday as run_index_intraday_refresh
from ..core.pipeline import run_full_refresh
from ..core.universe import all_symbols, stock_meta
from ..data import csv_store, event_calendar, news_rss, vix as vix_data
from ..db import session_scope
from ..live_analysis import movers as movers_mod
from ..live_analysis import regime as regime_mod
from ..live_analysis import config as live_cfg
from ..models.live_analysis_orm import LiveMarketSnapshot
from ..models.orm import Signal, Snapshot, Stock

log = logging.getLogger(__name__)

DISCLAIMER = "Research and decision-support only. Not financial advice."


# ---------------------------------------------------------------------------
# Data tools
# ---------------------------------------------------------------------------
def refresh_stocks_impl(force_full: bool = False) -> Dict[str, Any]:
    """Run the EOD stock pipeline (incremental by default)."""
    try:
        result = run_full_refresh(force_full=force_full)
        return {
            "fetched_symbols": result.fetched_symbols,
            "signals_generated": result.signals_generated,
            "errors": result.errors,
            "duration_s": (result.finished_at - result.started_at).total_seconds(),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("refresh_stocks_impl failed")
        return {"error": str(exc)}


def refresh_indices_intraday_impl() -> Dict[str, Any]:
    """Run the intraday index refresh (5-min OHLCV + signals)."""
    try:
        return {"result": run_index_intraday_refresh()}
    except Exception as exc:  # noqa: BLE001
        log.exception("refresh_indices_intraday_impl failed")
        return {"error": str(exc)}


def cache_status_impl() -> Dict[str, Any]:
    """List cached symbols + last bar date — useful for the data agent's
    self-check before/after a refresh."""
    try:
        out = []
        for sym in csv_store.list_cached_symbols():
            last = csv_store.last_date(sym)
            out.append({"symbol": sym, "last_date": last.isoformat() if last else None})
        out.sort(key=lambda r: r["symbol"])
        return {"count": len(out), "symbols": out}
    except Exception as exc:  # noqa: BLE001
        log.exception("cache_status_impl failed")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Analysis tools
# ---------------------------------------------------------------------------
def _rule_based_cards(top_k: int) -> List[Dict[str, Any]]:
    name_map = {m["symbol"]: m["name"] for m in stock_meta()}
    cards = _run_rule_based(name_map)
    return cards[:top_k]


def _ml_cards(infer_callable: Callable, top_k: int) -> List[Dict[str, Any]]:
    name_map = {m["symbol"]: m["name"] for m in stock_meta()}
    return infer_callable(name_map=name_map, top_k=top_k)


def rank_methods_impl(top_k: int = 15) -> Dict[str, Any]:
    """Run all four methods and return per-method top lists.

    A failed method (e.g. LSTM not trained yet) returns `{"error": "..."}`
    in its slot so the analysis agent can still finish without it.
    """
    out: Dict[str, Any] = {"methods": {}, "ran_at": datetime.now(timezone.utc).isoformat()}

    methods: Dict[str, Callable[[], List[Dict[str, Any]]]] = {
        "rule_based": lambda: _rule_based_cards(top_k),
        "rf": lambda: _ml_cards(ml_rf.infer, top_k) if ml_rf.is_ready() else [],
        "gbm": lambda: _ml_cards(ml_gbm.infer, top_k) if ml_gbm.is_ready() else [],
        "lstm": lambda: _ml_cards(ml_lstm.infer, top_k) if ml_lstm.is_ready() else [],
    }
    for name, fn in methods.items():
        try:
            out["methods"][name] = fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("rank_methods_impl: %s failed", name)
            out["methods"][name] = {"error": str(exc)}
    return out


def consensus_picks_impl(top_k: int = 10, min_votes: int = 2) -> List[Dict[str, Any]]:
    """Symbols showing up in >= `min_votes` method top lists, ranked by mean
    confidence. Each row keeps the per-method confidence so the UI can show
    the breakdown."""
    methods_out = rank_methods_impl(top_k=15)
    methods_dict: Dict[str, Any] = methods_out.get("methods", {})

    votes: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"votes": [], "confidences": {}, "directions": {}, "regime": None,
                 "close": None, "name": None, "categories": []}
    )
    for method_name, cards in methods_dict.items():
        if not isinstance(cards, list):
            continue
        for card in cards:
            sym = card.get("symbol")
            if not sym:
                continue
            slot = votes[sym]
            slot["votes"].append(method_name)
            slot["confidences"][method_name] = float(card.get("confidence") or 0.0)
            slot["directions"][method_name] = card.get("direction") or "NEUTRAL"
            slot["regime"] = slot["regime"] or card.get("regime")
            slot["close"] = slot["close"] or card.get("close")
            slot["name"] = slot["name"] or card.get("name")
            cat = card.get("category")
            if cat and cat not in slot["categories"]:
                slot["categories"].append(cat)

    rows: List[Dict[str, Any]] = []
    for sym, info in votes.items():
        if len(info["votes"]) < min_votes:
            continue
        confidences = list(info["confidences"].values())
        mean_conf = sum(confidences) / max(len(confidences), 1)
        # Score = mean confidence * vote weight (more methods agreeing -> higher score).
        # Normalised so a unanimous 4-method 1.0 confidence pick scores 100.
        score = round(mean_conf * (len(info["votes"]) / 4.0) * 100.0, 2)
        rows.append({
            "symbol": sym,
            "name": info["name"],
            "votes": info["votes"],
            "vote_count": len(info["votes"]),
            "mean_confidence": round(mean_conf, 3),
            "score": score,
            "confidences": info["confidences"],
            "directions": info["directions"],
            "regime": info["regime"],
            "close": info["close"],
            "categories": info["categories"],
        })

    rows.sort(key=lambda r: (-r["vote_count"], -r["score"]))
    return rows[:top_k]


def screener_signals_impl(
    category: Optional[str] = None,
    min_score: float = 0.0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Latest persisted screener signals (post EOD pipeline). Wraps
    `repository.latest_signals` so the AnalysisAgent can ground its summary
    in the same numbers the /screener page renders."""
    try:
        with session_scope() as db:
            from ..data import repository as repo
            sigs = repo.latest_signals(db, category=category, min_score=min_score)
            out: List[Dict[str, Any]] = []
            for s in sigs[:limit]:
                out.append({
                    "symbol": s.symbol,
                    "category": s.category,
                    "score": float(s.score),
                    "confidence": float(s.confidence),
                    "entry": s.entry,
                    "stop_loss": s.stop_loss,
                    "target_1": s.target_1,
                    "invalidation": s.invalidation,
                    "reasons": list(s.reasons_json or [])[:5],
                })
            return out
    except Exception as exc:  # noqa: BLE001
        log.exception("screener_signals_impl failed")
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Market context tools
# ---------------------------------------------------------------------------
def vix_level_impl() -> Dict[str, Any]:
    """India VIX latest print + band (NORMAL/ELEVATED/PANIC)."""
    snap = vix_data.fetch_vix()
    return {
        "value": snap.value,
        "band": snap.band,
        "source": snap.source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def market_regime_impl() -> Dict[str, Any]:
    """Use the existing live_analysis regime classifier on the most recent
    ^NSEI samples persisted by the live tick. Returns UNKNOWN if the live
    layer has not run yet (e.g. fresh DB)."""
    try:
        with session_scope() as db:
            cfg = live_cfg.snapshot(db)
            recent = list(db.scalars(
                select(LiveMarketSnapshot)
                .order_by(desc(LiveMarketSnapshot.ts))
                .limit(8)
            ))
            window: List[float] = []
            for snap in reversed(recent):
                if snap.nifty_last is not None:
                    window.append(float(snap.nifty_last))
            result = regime_mod.classify_market(window, cfg=cfg)
            return {
                "regime": result.regime,
                "nifty_last": result.last,
                "z_score": result.z,
                "slope": result.slope,
                "vwap_dev": result.vwap_dev,
                "samples_used": len(window),
            }
    except Exception as exc:  # noqa: BLE001
        log.exception("market_regime_impl failed")
        return {"regime": "UNKNOWN", "error": str(exc)}


def news_headlines_impl(limit: int = 10) -> List[Dict[str, Any]]:
    """RSS headlines from configured market feeds, deduped, recency-sorted."""
    try:
        rows = news_rss.fetch_headlines(limit=limit)
        return [
            {"title": h.title, "link": h.link, "source": h.source, "published": h.published}
            for h in rows
        ]
    except Exception as exc:  # noqa: BLE001
        log.exception("news_headlines_impl failed")
        return [{"error": str(exc)}]


def sector_rotation_impl() -> List[Dict[str, Any]]:
    """Aggregate today's screener signals by Stock.sector and rank by total
    score. Surfaces which sectors have the most/strongest active setups."""
    try:
        with session_scope() as db:
            from ..data import repository as repo
            sigs = repo.latest_signals(db)
            if not sigs:
                return []
            sym_to_sector: Dict[str, str] = {}
            for stock in db.scalars(select(Stock)):
                sym_to_sector[stock.symbol] = stock.sector or "Unknown"

            agg: Dict[str, Dict[str, Any]] = defaultdict(
                lambda: {"sector": "", "count": 0, "total_score": 0.0,
                         "mean_score": 0.0, "top_symbols": []}
            )
            for s in sigs:
                sec = sym_to_sector.get(s.symbol, "Unknown")
                slot = agg[sec]
                slot["sector"] = sec
                slot["count"] += 1
                slot["total_score"] += float(s.score)
                if len(slot["top_symbols"]) < 3:
                    slot["top_symbols"].append({
                        "symbol": s.symbol, "score": float(s.score),
                        "category": s.category,
                    })

            rows = list(agg.values())
            for r in rows:
                r["mean_score"] = round(r["total_score"] / max(r["count"], 1), 2)
                r["total_score"] = round(r["total_score"], 2)
            rows.sort(key=lambda r: -r["total_score"])
            return rows
    except Exception as exc:  # noqa: BLE001
        log.exception("sector_rotation_impl failed")
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Monitoring tools
# ---------------------------------------------------------------------------
def live_movers_impl(k: int = 15) -> Dict[str, Any]:
    """Today's Nifty 50 intraday movers (Upstox-first, yfinance fallback).
    Reuses the same scoring function as `/method-analysis/live-movers`."""
    try:
        name_map = {m["symbol"]: m["name"] for m in stock_meta()}
        symbols = all_symbols()
        with session_scope() as db:
            baseline = _baseline_prev_close_avg_vol(db, symbols)
        ltps, volumes, prev_closes_feed, source = _fetch_quotes_nifty50(symbols)

        inputs: List[movers_mod.MoverInput] = []
        for sym in symbols:
            last = ltps.get(sym)
            if not last or last <= 0:
                continue
            prev_close, avg_vol = baseline.get(sym, (0.0, 0))
            prev_close = prev_closes_feed.get(sym, prev_close) or prev_close
            if prev_close <= 0:
                continue
            inputs.append(movers_mod.MoverInput(
                symbol=sym, last_price=float(last), prev_close=float(prev_close),
                volume=int(volumes.get(sym, 0)), avg_volume=max(avg_vol, 1),
            ))
        ranked = movers_mod.rank_top_k(inputs, k=max(1, min(k, 50)))
        return {
            "movers": [
                {"rank": m.rank, "symbol": m.symbol, "name": name_map.get(m.symbol),
                 "last_price": m.last_price, "pct_change": m.pct_change,
                 "rvol": m.rvol, "score": m.score}
                for m in ranked
            ],
            "source": source,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("live_movers_impl failed")
        return {"error": str(exc)}


def refresh_verification_impl() -> Dict[str, Any]:
    """Run one verification pass on persisted screener signals (CONFIRMED /
    WEAKENING / INVALIDATED / STRENGTHENED)."""
    try:
        result = live_verif_core.run_live_verification()
        return {
            "signals_evaluated": result.signals_evaluated,
            "rows_upserted": result.rows_upserted,
            "by_status": dict(result.by_status),
            "source": result.source,
            "errors": result.errors,
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("refresh_verification_impl failed")
        return {"error": str(exc)}


def check_invalidations_impl(prev_top_picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compare the latest LTPs against the invalidation level on each prior
    top pick. Returns rows for symbols whose live price has crossed below
    (LONG) or above (SHORT) the recorded invalidation."""
    if not prev_top_picks:
        return []
    try:
        from ..data import live_quotes
        symbols = [p.get("symbol") for p in prev_top_picks if p.get("symbol")]
        if not symbols:
            return []
        ltps = live_quotes.fetch_live_prices(symbols)
        breaches: List[Dict[str, Any]] = []
        for pick in prev_top_picks:
            sym = pick.get("symbol")
            inv = pick.get("invalidation")
            direction = (pick.get("direction") or "LONG").upper()
            ltp = ltps.get(sym)
            if not sym or inv is None or ltp is None:
                continue
            if direction == "LONG" and ltp < float(inv):
                breaches.append({
                    "symbol": sym, "direction": direction,
                    "invalidation": float(inv), "live_price": float(ltp),
                    "reason": "LTP crossed below invalidation",
                })
            elif direction == "SHORT" and ltp > float(inv):
                breaches.append({
                    "symbol": sym, "direction": direction,
                    "invalidation": float(inv), "live_price": float(ltp),
                    "reason": "LTP crossed above invalidation",
                })
        return breaches
    except Exception as exc:  # noqa: BLE001
        log.exception("check_invalidations_impl failed")
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Informant tool — upcoming events (earnings, ex-div, F&O expiry, macro)
# ---------------------------------------------------------------------------
def upcoming_events_impl(days_ahead: int = 5) -> Dict[str, Any]:
    """Return the next-N-days event calendar for the Nifty 50 universe.

    Wraps `data.event_calendar.fetch_upcoming_events`, which combines
    yfinance per-symbol earnings/ex-dividend dates with a static macro
    registry (RBI MPC, Fed FOMC, monthly auto sales) and computed F&O
    monthly expiries. Events are deduped, date-sorted, and clamped to
    the lookahead window.

    Errors are swallowed into the response so the orchestrator's deep
    cycle never fails on a yfinance hiccup.
    """
    try:
        name_map = {m["symbol"]: m["name"] for m in stock_meta()}
        symbols = all_symbols()
        events = event_calendar.fetch_upcoming_events(
            symbols=symbols,
            name_map=name_map,
            days_ahead=int(days_ahead),
        )
        # Aggregate the union of symbols across all events for the dashboard
        # "watch list" — these are the stocks that are likely to move.
        watch: List[str] = []
        for ev in events:
            for s in ev.symbols:
                if s != "MARKET" and s not in watch:
                    watch.append(s)
        return {
            "events": [ev.to_dict() for ev in events],
            "watch_symbols": watch,
            "days_ahead": int(days_ahead),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("upcoming_events_impl failed")
        return {"events": [], "watch_symbols": [], "error": str(exc)}


def latest_snapshot_close_impl(symbol: str) -> Optional[float]:
    """Helper used by the head agent's stitch path to backfill close prices
    for picks that lack a `close` field."""
    try:
        with session_scope() as db:
            snap = db.scalar(
                select(Snapshot)
                .where(Snapshot.symbol == symbol)
                .order_by(desc(Snapshot.run_at))
                .limit(1)
            )
            return float(snap.close) if snap else None
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "DISCLAIMER",
    "refresh_stocks_impl",
    "refresh_indices_intraday_impl",
    "cache_status_impl",
    "rank_methods_impl",
    "consensus_picks_impl",
    "screener_signals_impl",
    "vix_level_impl",
    "market_regime_impl",
    "news_headlines_impl",
    "sector_rotation_impl",
    "live_movers_impl",
    "refresh_verification_impl",
    "check_invalidations_impl",
    "latest_snapshot_close_impl",
    "upcoming_events_impl",
]
