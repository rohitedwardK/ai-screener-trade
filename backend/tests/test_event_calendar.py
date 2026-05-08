"""Deterministic tests for `app.data.event_calendar`.

We never hit yfinance. yfinance per-symbol calls are stubbed via monkeypatch
on `_fetch_calendar_for_symbol` so each test owns its own calendar shape and
the assertions stay completely reproducible.
"""
from __future__ import annotations

from datetime import date

import pytest


# ---------------------------------------------------------------------------
# Date math: last Thursday of any given month
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "year,month,expected",
    [
        # Hand-computed reference dates — all are Thursdays and the last
        # Thursday of their month per the Indian calendar.
        (2026, 1, date(2026, 1, 29)),
        (2026, 2, date(2026, 2, 26)),
        (2026, 3, date(2026, 3, 26)),
        (2026, 4, date(2026, 4, 30)),
        (2026, 5, date(2026, 5, 28)),
        (2026, 6, date(2026, 6, 25)),
        (2026, 7, date(2026, 7, 30)),
        (2026, 8, date(2026, 8, 27)),
        # Edge: month ends on a Thursday — the last Thursday IS the last day.
        (2024, 10, date(2024, 10, 31)),
        # Edge: December rolls to next year in the helper.
        (2025, 12, date(2025, 12, 25)),
    ],
)
def test_last_thursday_matches_known_dates(year: int, month: int, expected: date):
    from app.data import event_calendar

    out = event_calendar._last_thursday(year, month)
    assert out == expected
    assert out.weekday() == 3  # 3 == Thursday


def test_expiry_dates_in_window_straddles_month_boundary():
    from app.data import event_calendar

    # Pick a date that puts the window across April->May 2026.
    today = date(2026, 4, 28)
    out = event_calendar._expiry_dates_in_window(today, days_ahead=10)
    # Window: 2026-04-28 .. 2026-05-08. Last-Thursday-of-April is 2026-04-30
    # (in window). Last-Thursday-of-May is 2026-05-28 (out of window).
    assert out == [date(2026, 4, 30)]


def test_expiry_dates_in_window_returns_empty_when_outside_horizon():
    from app.data import event_calendar

    today = date(2026, 4, 5)  # well before April expiry
    out = event_calendar._expiry_dates_in_window(today, days_ahead=3)
    assert out == []


# ---------------------------------------------------------------------------
# Public fetch path: event merging, dedupe, sorting, days_until clamp
# ---------------------------------------------------------------------------
def test_fetch_upcoming_events_merges_per_symbol_and_macro(monkeypatch):
    """Two symbols, each with an upcoming earnings + ex-dividend, plus the
    macro registry / expiry computation. We assert the final list is
    date-sorted, deduped, and the days_until field is clamped non-negative.
    """
    from app.data import event_calendar

    event_calendar.reset_cache()

    # Anchor "today" so the assertions are reproducible. The 5-day window
    # below: 2026-05-08 .. 2026-05-13.
    today = date(2026, 5, 8)

    fake_calendars = {
        "RELIANCE.NS": {
            "Earnings Date": date(2026, 5, 12),
            "Ex-Dividend Date": date(2026, 5, 9),
        },
        "INFY.NS": {
            "Earnings Date": date(2026, 5, 11),
            # Ex-div is OUT of window (too far) — must be filtered out.
            "Ex-Dividend Date": date(2026, 6, 1),
        },
        # Stale symbol — entirely past dates, must contribute zero events.
        "TCS.NS": {
            "Earnings Date": date(2025, 4, 1),
        },
    }

    def fake_fetch(symbol):
        return fake_calendars.get(symbol, {})

    monkeypatch.setattr(event_calendar, "_fetch_calendar_for_symbol", fake_fetch)

    name_map = {"RELIANCE.NS": "Reliance", "INFY.NS": "Infosys", "TCS.NS": "TCS"}

    events = event_calendar.fetch_upcoming_events(
        symbols=["RELIANCE.NS", "INFY.NS", "TCS.NS"],
        name_map=name_map,
        days_ahead=5,
        today=today,
        force=True,
    )

    # All event dates fall in the window.
    assert all(e.date >= today.isoformat() for e in events)
    horizon = "2026-05-13"
    assert all(e.date <= horizon for e in events)

    # days_until is non-negative and matches the date math.
    for e in events:
        assert e.days_until >= 0
        assert e.days_until <= 5

    # Sorted ascending by date.
    dates = [e.date for e in events]
    assert dates == sorted(dates)

    titles = [e.title for e in events]
    assert "Earnings — Reliance" in titles
    assert "Earnings — Infosys" in titles
    assert "Ex-dividend — Reliance" in titles
    # Out-of-window dividend was filtered.
    assert all("Ex-dividend — Infosys" not in t for t in titles)
    # Past earnings was filtered.
    assert all("Earnings — TCS" not in t for t in titles)


def test_fetch_upcoming_events_dedupes_repeated_keys(monkeypatch):
    """The dedupe key is (date, category, title). If a symbol's calendar
    appears twice (e.g. yfinance returns dups across endpoints) we keep
    one entry, not two."""
    from app.data import event_calendar

    event_calendar.reset_cache()
    today = date(2026, 5, 8)

    monkeypatch.setattr(
        event_calendar,
        "_fetch_calendar_for_symbol",
        lambda sym: {"Earnings Date": date(2026, 5, 11)},
    )

    # Same symbol passed twice — yfinance fetcher returns the same date both
    # times. The dedupe must keep exactly one event.
    events = event_calendar.fetch_upcoming_events(
        symbols=["RELIANCE.NS", "RELIANCE.NS"],
        name_map={"RELIANCE.NS": "Reliance"},
        days_ahead=5,
        today=today,
        force=True,
    )
    earnings = [e for e in events if e.category == event_calendar.CATEGORY_EARNINGS]
    assert len(earnings) == 1


def test_fetch_upcoming_events_handles_yfinance_empty_calendar(monkeypatch):
    """yfinance returns `None` / `{}` for symbols with no upcoming events.
    The fetcher must not raise and must still return macro events."""
    from app.data import event_calendar

    event_calendar.reset_cache()
    today = date(2026, 5, 8)

    monkeypatch.setattr(event_calendar, "_fetch_calendar_for_symbol", lambda sym: {})

    events = event_calendar.fetch_upcoming_events(
        symbols=["RELIANCE.NS"],
        name_map={},
        days_ahead=5,
        today=today,
        force=True,
    )
    # No per-symbol events; only macro registry / expiry events (if any in
    # this 5-day window). Empty list is acceptable.
    assert all(e.category != event_calendar.CATEGORY_EARNINGS for e in events)
    assert all(e.category != event_calendar.CATEGORY_DIVIDEND for e in events)


def test_fetch_upcoming_events_uses_cache_until_force_or_window_change(monkeypatch):
    from app.data import event_calendar

    event_calendar.reset_cache()
    today = date(2026, 5, 8)

    calls = {"count": 0}

    def fake_fetch(sym):
        calls["count"] += 1
        return {"Earnings Date": date(2026, 5, 12)}

    monkeypatch.setattr(event_calendar, "_fetch_calendar_for_symbol", fake_fetch)

    event_calendar.fetch_upcoming_events(
        symbols=["RELIANCE.NS"], name_map={}, days_ahead=5, today=today, force=False,
    )
    first_calls = calls["count"]

    # Same window, no force -> served from cache, no new yfinance hits.
    event_calendar.fetch_upcoming_events(
        symbols=["RELIANCE.NS"], name_map={}, days_ahead=5, today=today, force=False,
    )
    assert calls["count"] == first_calls

    # Different window -> cache invalidated, fetch again.
    event_calendar.fetch_upcoming_events(
        symbols=["RELIANCE.NS"], name_map={}, days_ahead=10, today=today, force=False,
    )
    assert calls["count"] > first_calls


# ---------------------------------------------------------------------------
# Tool wrapper smoke test
# ---------------------------------------------------------------------------
def test_upcoming_events_impl_aggregates_watch_symbols(monkeypatch):
    """`upcoming_events_impl` must produce a watch_symbols list that's the
    union of per-event symbols, excluding the MARKET sentinel."""
    from app.agents import tools as tools_mod
    from app.data import event_calendar

    event_calendar.reset_cache()

    monkeypatch.setattr(
        tools_mod, "all_symbols", lambda: ["RELIANCE.NS", "INFY.NS"]
    )
    monkeypatch.setattr(
        tools_mod,
        "stock_meta",
        lambda: [
            {"symbol": "RELIANCE.NS", "name": "Reliance"},
            {"symbol": "INFY.NS", "name": "Infosys"},
        ],
    )

    fake_events = [
        event_calendar.UpcomingEvent(
            date="2026-05-12", days_until=4, category="EARNINGS",
            title="Earnings — Reliance", symbols=["RELIANCE.NS"],
            source="yfinance", impact="HIGH",
        ),
        event_calendar.UpcomingEvent(
            date="2026-05-12", days_until=4, category="EXPIRY",
            title="F&O monthly expiry (last Thursday)", symbols=["MARKET"],
            source="computed", impact="MEDIUM",
        ),
    ]

    monkeypatch.setattr(
        event_calendar,
        "fetch_upcoming_events",
        lambda **kwargs: fake_events,
    )

    out = tools_mod.upcoming_events_impl(days_ahead=5)
    assert len(out["events"]) == 2
    # MARKET sentinel must not leak into watch_symbols.
    assert out["watch_symbols"] == ["RELIANCE.NS"]
    assert out["days_ahead"] == 5
