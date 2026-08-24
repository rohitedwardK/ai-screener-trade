"""Weekly expiry helpers.

Lightweight reimplementation of the parent app's `next_weekly_expiry` so
the live-market service stays self-contained. After 14:30 IST on the
expiry day itself we roll forward by a week so the picker doesn't
recommend a strike with under an hour of life.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

_WEEKDAY_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}

_EXPIRY_DAY_CUTOFF = time(14, 30)


def next_weekly_expiry(
    weekly_expiry_day: Optional[str],
    today: date,
    *,
    now_time: Optional[time] = None,
) -> date:
    target_idx = _WEEKDAY_INDEX.get(weekly_expiry_day or "Thursday", 3)
    today_idx = today.weekday()
    delta = (target_idx - today_idx) % 7
    if delta == 0:
        if now_time is None or now_time >= _EXPIRY_DAY_CUTOFF:
            delta = 7
    return today + timedelta(days=delta)


def now_ist() -> datetime:
    """Naive IST wall-clock derived from UTC + 5:30.

    APScheduler runs in process-local TZ on Windows; the scheduler tick
    explicitly reuses this so the expiry-day rollover behaves the same
    in tests (UTC) and prod (IST).
    """
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


__all__ = ["next_weekly_expiry", "now_ist"]
