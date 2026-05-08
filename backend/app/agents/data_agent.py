"""DataAgent — keeps the CSV cache + SQLite mirror in sync.

Plain Python class wrapping `tools.refresh_stocks_impl` and friends. The
"agent" abstraction here is structural — each worker has a clear role and
a small, well-defined tool set. The head agent delegates by calling
`run()` on each worker rather than via natural-language tool selection,
which is faster and more reliable on a 3B local model.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .tools import (
    cache_status_impl,
    refresh_indices_intraday_impl,
    refresh_stocks_impl,
)

log = logging.getLogger(__name__)


def run(force_full: bool = False) -> Dict[str, Any]:
    """Refresh stock CSV cache + intraday index OHLCV, then verify."""
    log.info("DataAgent: refresh_stocks force_full=%s", force_full)
    refresh = refresh_stocks_impl(force_full=force_full)
    intraday = refresh_indices_intraday_impl()
    status = cache_status_impl()
    return {
        "refresh_stocks": refresh,
        "refresh_indices_intraday": intraday,
        "cache_status": status,
    }


# Backwards-compatible alias for code that already imports run_deterministic.
run_deterministic = run


__all__ = ["run", "run_deterministic"]
