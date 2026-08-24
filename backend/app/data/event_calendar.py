"""Upcoming-events calendar for the InformantAgent.

Surfaces market-moving events in a forward-looking window (default 5 days)
across four categories:

    EARNINGS   per-symbol earnings announcement (yfinance `Ticker.calendar`)
    DIVIDEND   per-symbol ex-dividend date (yfinance `Ticker.calendar`)
    EXPIRY     F&O monthly expiry — last Thursday of each calendar month
    MACRO      RBI MPC, Fed FOMC, monthly auto-sales prints, Budget,
               quarterly inflation prints. Hardcoded registry kept current
               by the maintainer; refreshing it is a quarterly task.

Why it lives in `data/` not `analysis/`: it is an external feed wrapper
(yfinance + a small static registry), not deterministic indicator math.
The InformantAgent calls `fetch_upcoming_events` and the orchestrator
includes the result in the daily briefing payload.

Caching: 12-hour in-process memo (events do not change intra-day).
Per-symbol yfinance failures are isolated — one slow ticker never blocks
the rest of the universe.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import yfinance as yf

from . import yf_client

log = logging.getLogger(__name__)

CATEGORY_EARNINGS = "EARNINGS"
CATEGORY_DIVIDEND = "DIVIDEND"
CATEGORY_EXPIRY = "EXPIRY"
CATEGORY_MACRO = "MACRO"

IMPACT_HIGH = "HIGH"
IMPACT_MEDIUM = "MEDIUM"
IMPACT_LOW = "LOW"

# 12 hours — earnings calendars don't update intra-day. The fast monitor
# pulls events on a schedule via the orchestrator's deep cycle, not directly.
_CACHE_TTL_SECONDS = 12 * 60 * 60.0


@dataclass(frozen=True)
class UpcomingEvent:
    """One row the dashboard renders.

    `symbols` lists the stocks expected to react. For per-symbol events
    (earnings, ex-dividend) it's a single-element list; for macro events
    it's the curated set of sector leaders we know respond to that print.
    `MARKET` is a sentinel for events that move the entire index.
    """

    date: str  # ISO YYYY-MM-DD
    days_until: int
    category: str
    title: str
    symbols: List[str]
    source: str
    impact: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Macro registry
# ---------------------------------------------------------------------------
# Sector baskets used by macro events. Kept in sync with the Nifty 50
# universe in `core/universe.py`; if a symbol is dropped from the index,
# remove it here too.
_FINANCIALS = [
    "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS",
    "SBIN.NS", "INDUSINDBK.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS",
    "SHRIRAMFIN.NS", "HDFCLIFE.NS", "SBILIFE.NS",
]
_IT_EXPORTERS = [
    "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTM.NS",
]
_AUTO = [
    "MARUTI.NS", "TMPV.NS", "M&M.NS", "BAJAJ-AUTO.NS",
    "EICHERMOT.NS", "HEROMOTOCO.NS",
]
_ENERGY_PAINT = ["RELIANCE.NS", "ONGC.NS", "BPCL.NS", "ASIANPAINT.NS"]


_TITLE_RBI_MPC = "RBI MPC rate decision"
_TITLE_FOMC = "US FOMC rate decision"
_TITLE_AUTO_SALES = "Monthly auto sales prints"
_TITLE_FNO_EXPIRY = "F&O monthly expiry (last Thursday)"

# Macro events for ~6 months out. Refresh quarterly. Dates are best-effort
# from RBI/FOMC official calendars; the agent will silently drop events
# in the past on every fetch so stale entries are not a correctness risk.
# Format: (date, title, affected_symbols, impact).
_MACRO_REGISTRY: List[tuple[date, str, List[str], str]] = [
    # --- RBI MPC (bi-monthly) ---
    (date(2026, 6, 4),  _TITLE_RBI_MPC, _FINANCIALS, IMPACT_HIGH),
    (date(2026, 8, 6),  _TITLE_RBI_MPC, _FINANCIALS, IMPACT_HIGH),
    (date(2026, 10, 1), _TITLE_RBI_MPC, _FINANCIALS, IMPACT_HIGH),
    (date(2026, 12, 5), _TITLE_RBI_MPC, _FINANCIALS, IMPACT_HIGH),

    # --- US FOMC (8/year) ---
    (date(2026, 6, 17),  _TITLE_FOMC, _IT_EXPORTERS, IMPACT_HIGH),
    (date(2026, 7, 29),  _TITLE_FOMC, _IT_EXPORTERS, IMPACT_HIGH),
    (date(2026, 9, 16),  _TITLE_FOMC, _IT_EXPORTERS, IMPACT_HIGH),
    (date(2026, 11, 4),  _TITLE_FOMC, _IT_EXPORTERS, IMPACT_HIGH),
    (date(2026, 12, 16), _TITLE_FOMC, _IT_EXPORTERS, IMPACT_HIGH),
]


def _monthly_auto_sales_dates(today: date, days_ahead: int) -> List[tuple[date, str, List[str], str]]:
    """Auto OEMs typically report monthly volumes on the 1st business day
    of every month. We approximate as the 1st calendar day; if it lands on
    a weekend, push to the next Monday."""
    out = []
    cursor = date(today.year, today.month, 1)
    while cursor <= today + timedelta(days=days_ahead + 5):
        # Push weekend to Monday (Sat -> +2, Sun -> +1).
        wd = cursor.weekday()
        if wd == 5:
            cursor = cursor + timedelta(days=2)
        elif wd == 6:
            cursor = cursor + timedelta(days=1)
        out.append((cursor, _TITLE_AUTO_SALES, list(_AUTO), IMPACT_MEDIUM))
        # Advance to next month's 1st.
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return out


def _last_thursday(year: int, month: int) -> date:
    """Last Thursday of the calendar month — the F&O monthly expiry day
    (NSE convention, ignoring the rare Wednesday-shift on a Thursday holiday).

    Pure date math so the function is trivial to unit-test.
    """
    # Walk backwards from the last day of the month to the most recent Thursday.
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    last_day = first_of_next - timedelta(days=1)
    # Thursday == weekday 3.
    offset = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=offset)


def _expiry_dates_in_window(today: date, days_ahead: int) -> List[date]:
    """All F&O monthly expiry dates that fall in the [today, today+days_ahead]
    window. Usually 0-1 entries for a 5-day window."""
    out: List[date] = []
    # Check current and next month — 5 day window can straddle a month boundary.
    for delta_month in range(0, 2):
        y, m = today.year, today.month + delta_month
        if m > 12:
            m -= 12
            y += 1
        exp = _last_thursday(y, m)
        if today <= exp <= today + timedelta(days=days_ahead):
            out.append(exp)
    return out


# ---------------------------------------------------------------------------
# yfinance per-symbol helpers
# ---------------------------------------------------------------------------
def _coerce_date(value: Any) -> Optional[date]:
    """yfinance returns pandas.Timestamp / datetime / list / dict — flatten
    to a `date` or None. Returns None on any parse failure."""
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, dict):
        # Some yfinance versions return {"raw": ts, "fmt": "..."}.
        value = value.get("fmt") or value.get("raw")
        if value is None:
            return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date() if isinstance(value, datetime) else pd.Timestamp(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return pd.to_datetime(value).date()
        except (ValueError, TypeError):
            return None
    if isinstance(value, (int, float)):
        # Unix timestamp seconds.
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (ValueError, OSError):
            return None
    return None


def _fetch_calendar_for_symbol(symbol: str) -> Dict[str, Any]:
    """One yfinance `Ticker.calendar` call. Best-effort; empty dict on any
    failure (Yahoo 404, rate limit, network blip, schema drift).

    yfinance's calendar shape differs by version — newer (1.3+) returns a
    dict with keys like "Earnings Date" / "Ex-Dividend Date" / "Dividend Date"
    pointing to either a Timestamp, datetime, list of dates, or NaT. We
    normalise downstream in `_coerce_date`.
    """
    yf_client.pace()
    try:
        cal = yf.Ticker(symbol).calendar
    except Exception as exc:  # noqa: BLE001 — defensive
        log.debug("calendar fetch failed for %s: %s", symbol, exc)
        return {}
    if cal is None:
        return {}
    # Some yfinance versions still return a DataFrame; convert to dict.
    if isinstance(cal, pd.DataFrame):
        try:
            cal = cal.to_dict("list")
        except Exception:  # noqa: BLE001
            return {}
    return cal if isinstance(cal, dict) else {}


def _per_symbol_events(
    symbols: Sequence[str],
    today: date,
    days_ahead: int,
    name_map: Dict[str, str],
) -> List[UpcomingEvent]:
    """Pull earnings + ex-dividend dates per symbol within the window.

    yfinance is slow (~0.3s per symbol after pacing) so a 50-symbol scan
    takes ~15s. Acceptable inside the 15-min deep cycle and only happens
    once per cache TTL.
    """
    horizon = today + timedelta(days=days_ahead)
    out: List[UpcomingEvent] = []
    for sym in symbols:
        cal = _fetch_calendar_for_symbol(sym)
        if not cal:
            continue
        name = name_map.get(sym, sym)

        earn = _coerce_date(cal.get("Earnings Date"))
        if earn and today <= earn <= horizon:
            out.append(UpcomingEvent(
                date=earn.isoformat(),
                days_until=(earn - today).days,
                category=CATEGORY_EARNINGS,
                title=f"Earnings — {name}",
                symbols=[sym],
                source="yfinance",
                impact=IMPACT_HIGH,
            ))

        ex_div = _coerce_date(cal.get("Ex-Dividend Date"))
        if ex_div and today <= ex_div <= horizon:
            out.append(UpcomingEvent(
                date=ex_div.isoformat(),
                days_until=(ex_div - today).days,
                category=CATEGORY_DIVIDEND,
                title=f"Ex-dividend — {name}",
                symbols=[sym],
                source="yfinance",
                impact=IMPACT_LOW,
            ))
    return out


def _macro_events(today: date, days_ahead: int) -> List[UpcomingEvent]:
    """Combine the static registry with computed monthly events (auto sales,
    F&O expiries) and filter to the window."""
    horizon = today + timedelta(days=days_ahead)
    out: List[UpcomingEvent] = []

    for d, title, syms, impact in _MACRO_REGISTRY:
        if today <= d <= horizon:
            out.append(UpcomingEvent(
                date=d.isoformat(),
                days_until=(d - today).days,
                category=CATEGORY_MACRO,
                title=title,
                symbols=list(syms),
                source="macro_registry",
                impact=impact,
            ))

    for d, title, syms, impact in _monthly_auto_sales_dates(today, days_ahead):
        if today <= d <= horizon:
            out.append(UpcomingEvent(
                date=d.isoformat(),
                days_until=(d - today).days,
                category=CATEGORY_MACRO,
                title=title,
                symbols=list(syms),
                source="macro_registry",
                impact=impact,
            ))

    for exp in _expiry_dates_in_window(today, days_ahead):
        out.append(UpcomingEvent(
            date=exp.isoformat(),
            days_until=(exp - today).days,
            category=CATEGORY_EXPIRY,
            title=_TITLE_FNO_EXPIRY,
            symbols=["MARKET"],
            source="computed",
            impact=IMPACT_MEDIUM,
        ))

    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cached: List[UpcomingEvent] = []
_cached_at: float = 0.0
_cached_window: int = 0


def _dedupe_and_sort(events: Sequence[UpcomingEvent]) -> List[UpcomingEvent]:
    """Dedupe by (date, category, title) — symbols list can differ across
    sources but the same (date, title) means the same event."""
    seen: set[tuple[str, str, str]] = set()
    merged: List[UpcomingEvent] = []
    for ev in events:
        key = (ev.date, ev.category, ev.title)
        if key in seen:
            continue
        seen.add(key)
        merged.append(ev)
    merged.sort(key=lambda e: (e.date, e.category, e.title))
    return merged


def _cache_hit(now: float, window: int) -> Optional[List[UpcomingEvent]]:
    """Read-side of the in-process memo. Returns None when the cache is stale
    or for a different window. Holds the lock briefly."""
    with _lock:
        if _cached and _cached_window == window and (now - _cached_at) < _CACHE_TTL_SECONDS:
            return list(_cached)
        return None


def _store_cache(events: List[UpcomingEvent], window: int) -> None:
    global _cached, _cached_at, _cached_window
    with _lock:
        _cached = events
        _cached_at = time.monotonic()
        _cached_window = window


def fetch_upcoming_events(
    symbols: Sequence[str],
    *,
    name_map: Optional[Dict[str, str]] = None,
    days_ahead: int = 5,
    today: Optional[date] = None,
    force: bool = False,
) -> List[UpcomingEvent]:
    """Return a deduped, date-sorted list of events in [today, today+days_ahead].

    Args:
        symbols: per-symbol scan universe (typically Nifty 50)
        name_map: symbol -> friendly name for the event title
        days_ahead: lookahead horizon (default 5 to match the user's ask)
        today: override for deterministic tests; defaults to UTC today
        force: bypass the 12-hour in-process cache

    Returns:
        Up to ~30 events. Empty list on a totally empty calendar (not an error).
    """
    today = today or datetime.now(timezone.utc).date()
    name_map = dict(name_map or {})

    if not force:
        cached = _cache_hit(time.monotonic(), days_ahead)
        if cached is not None:
            return cached

    macro = _macro_events(today, days_ahead)
    per_sym = _per_symbol_events(symbols, today, days_ahead, name_map)
    merged = _dedupe_and_sort(macro + per_sym)
    _store_cache(merged, days_ahead)
    return merged


def reset_cache() -> None:
    """Test hook so deterministic pytest fixtures can clear in-process state."""
    global _cached, _cached_at, _cached_window
    with _lock:
        _cached = []
        _cached_at = 0.0
        _cached_window = 0


__all__ = [
    "UpcomingEvent",
    "CATEGORY_EARNINGS",
    "CATEGORY_DIVIDEND",
    "CATEGORY_EXPIRY",
    "CATEGORY_MACRO",
    "IMPACT_HIGH",
    "IMPACT_MEDIUM",
    "IMPACT_LOW",
    "fetch_upcoming_events",
    "reset_cache",
    "_last_thursday",
    "_expiry_dates_in_window",
]
