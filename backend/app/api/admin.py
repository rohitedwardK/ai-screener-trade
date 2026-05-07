"""Admin endpoints (manual refresh trigger)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query

from ..core.pipeline import run_full_refresh
from ..core.index_pipeline import (
    refresh_intraday as run_index_intraday_refresh,
    run_full_refresh as run_index_full_refresh,
)
from ..data import csv_store, index_csv_store
from ..models.schemas import RefreshResult

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/refresh", response_model=RefreshResult)
def trigger_refresh(
    full: bool = Query(False, description="Force full re-download instead of incremental."),
) -> RefreshResult:
    """Run the refresh pipeline synchronously and return stats.

    Default mode is **incremental**: each symbol's cached CSV is read, only the
    new days are fetched, then merged. This is fast (~2–5s for 50 symbols once
    the cache is warm).

    Pass `?full=true` to force a complete 5y re-download for every symbol —
    use this after a major split / corporate action to refresh adjusted prices.
    """
    return run_full_refresh(force_full=full)


@router.post("/refresh-async")
def trigger_refresh_async(
    bg: BackgroundTasks,
    full: bool = Query(False),
) -> dict:
    """Schedule the refresh in the background and return immediately."""
    bg.add_task(run_full_refresh, force_full=full)
    return {"status": "scheduled", "mode": "full" if full else "incremental"}


@router.get("/cache-status")
def cache_status() -> dict:
    """Diagnostic: which symbols have cached CSVs and how fresh they are."""
    out = []
    for sym in csv_store.list_cached_symbols():
        last = csv_store.last_date(sym)
        df = csv_store.load(sym)
        out.append({
            "symbol": sym,
            "last_date": last.isoformat() if last else None,
            "rows": len(df),
        })
    out.sort(key=lambda r: r["symbol"])
    return {"count": len(out), "symbols": out}


# ---------- Index refresh ----------

@router.post("/refresh-indices")
def trigger_index_refresh(
    full: bool = Query(False, description="Force full re-download for indices."),
) -> dict:
    """Run the daily index refresh synchronously."""
    result = run_index_full_refresh(force_full=full)
    return {
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "fetched_symbols": result.fetched_symbols,
        "signals_generated": result.signals_generated,
        "errors": result.errors,
    }


@router.post("/refresh-indices-async")
def trigger_index_refresh_async(
    bg: BackgroundTasks,
    full: bool = Query(False),
) -> dict:
    bg.add_task(run_index_full_refresh, force_full=full)
    return {"status": "scheduled", "mode": "full" if full else "incremental", "scope": "indices"}


@router.post("/refresh-indices-intraday")
def trigger_index_intraday_refresh() -> dict:
    """Manually trigger the intraday index refresh."""
    return run_index_intraday_refresh()


@router.get("/index-cache-status")
def index_cache_status() -> dict:
    """Diagnostic: cached daily CSVs for indices."""
    out = []
    for sym in index_csv_store.list_cached():
        last = index_csv_store.last_date(sym)
        df = index_csv_store.load(sym)
        out.append({
            "symbol": sym,
            "last_date": last.isoformat() if last else None,
            "rows": len(df),
        })
    out.sort(key=lambda r: r["symbol"])
    return {"count": len(out), "symbols": out}
