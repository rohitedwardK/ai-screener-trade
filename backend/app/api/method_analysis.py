"""Method Analysis API — comparing Rule-Based / Random Forest / GBM / LSTM.

POST /method-analysis/train?method=rf|gbm|lstm
GET  /method-analysis/status
POST /method-analysis/run?method=rule_based|rf|gbm|lstm
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..analysis import ml_gbm, ml_rf, ml_lstm
from ..core.universe import all_symbols, stock_meta
from ..data import live_quotes, upstox_client
from ..db import session_scope
from ..live_analysis.movers import MoverInput, rank_top_k
from ..models.orm import Candle

log = logging.getLogger(__name__)
router = APIRouter(prefix="/method-analysis", tags=["method-analysis"])

# ---------------------------------------------------------------------------
# In-memory training state — one entry per trainable method.
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_train_status: Dict[str, dict] = {
    "rf": {
        "status": "idle",    # idle | training | ready | error
        "progress": 0.0,
        "message": "",
        "metric_label": "AUC",
        "metric_value": None,
        "error": None,
        "updated_at": None,
    },
    "gbm": {
        "status": "idle",
        "progress": 0.0,
        "message": "",
        "metric_label": "AUC",
        "metric_value": None,
        "error": None,
        "updated_at": None,
    },
    "lstm": {
        "status": "idle",
        "progress": 0.0,
        "message": "",
        "metric_label": "Val Acc",
        "metric_value": None,
        "error": None,
        "updated_at": None,
    },
}

# Pre-populate "ready" if model artefacts already exist on disk.
if ml_rf.is_ready():
    _train_status["rf"]["status"] = "ready"
# Legacy: old builds stored GBM weights in signal_ranker_rf.pkl — user should re-train RF + GBM separately.
if ml_gbm.is_ready():
    _train_status["gbm"]["status"] = "ready"
if ml_lstm.is_ready():
    _train_status["lstm"]["status"] = "ready"


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------
class MethodTrainStatus(BaseModel):
    status: str
    progress: float
    message: str
    metric_label: str
    metric_value: Optional[float]
    error: Optional[str]
    updated_at: Optional[str]


class AllMethodStatus(BaseModel):
    rule_based: MethodTrainStatus
    rf: MethodTrainStatus
    gbm: MethodTrainStatus
    lstm: MethodTrainStatus


class MethodSignalCard(BaseModel):
    symbol: str
    name: Optional[str]
    confidence: float
    direction: str
    category: Optional[str]
    regime: str
    close: float
    top_factors: List[str]


class MethodRunResult(BaseModel):
    method: str
    signals: List[MethodSignalCard]
    ran_at: str
    disclaimer: str


class LiveMoverRow(BaseModel):
    rank: int
    symbol: str
    name: Optional[str]
    last_price: float
    pct_change: float
    rvol: float
    score: float


class LiveMoversOut(BaseModel):
    movers: List[LiveMoverRow]
    source: str
    fetched_at: str
    disclaimer: str


# ---------------------------------------------------------------------------
# Background training worker
# ---------------------------------------------------------------------------
def _set_status(method: str, **kwargs) -> None:
    with _LOCK:
        _train_status[method].update(kwargs)
        _train_status[method]["updated_at"] = datetime.now(timezone.utc).isoformat()


def _run_rf_training() -> None:
    _set_status("rf", status="training", progress=0.0, message="Starting…", error=None)

    def cb(pct: float, msg: str = "") -> None:
        _set_status("rf", progress=round(pct, 3), message=msg)

    try:
        result = ml_rf.train(progress_cb=cb)
        _set_status(
            "rf",
            status="ready",
            progress=1.0,
            message="Training complete",
            metric_value=round(result.get("mean_auc", 0.0), 3),
        )
        log.info("Random Forest training complete — AUC %.3f", result.get("mean_auc", 0))
    except Exception as exc:
        log.exception("Random Forest training failed")
        _set_status("rf", status="error", error=str(exc), message="Training failed")


def _run_gbm_training() -> None:
    _set_status("gbm", status="training", progress=0.0, message="Starting…", error=None)

    def cb(pct: float, msg: str = "") -> None:
        _set_status("gbm", progress=round(pct, 3), message=msg)

    try:
        result = ml_gbm.train(progress_cb=cb)
        _set_status(
            "gbm",
            status="ready",
            progress=1.0,
            message="Training complete",
            metric_value=round(result.get("mean_auc", 0.0), 3),
        )
        log.info("GBM training complete — AUC %.3f", result.get("mean_auc", 0))
    except Exception as exc:
        log.exception("GBM training failed")
        _set_status("gbm", status="error", error=str(exc), message="Training failed")


def _run_lstm_training() -> None:
    _set_status("lstm", status="training", progress=0.0, message="Starting…", error=None)

    def cb(pct: float, msg: str = "") -> None:
        _set_status("lstm", progress=round(pct, 3), message=msg)

    try:
        result = ml_lstm.train(progress_cb=cb)
        _set_status(
            "lstm",
            status="ready",
            progress=1.0,
            message="Training complete",
            metric_value=round(result.get("best_val_acc", 0.0), 3),
        )
        log.info("LSTM training complete — val_acc %.3f", result.get("best_val_acc", 0))
    except Exception as exc:
        log.exception("LSTM training failed")
        _set_status("lstm", status="error", error=str(exc), message="Training failed")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/train")
def start_training(method: Literal["rf", "gbm", "lstm"]) -> MethodTrainStatus:
    """Start training the selected model in a background thread."""
    with _LOCK:
        current = _train_status[method]["status"]

    if current == "training":
        with _LOCK:
            return MethodTrainStatus(**_train_status[method])

    if method == "rf":
        target = _run_rf_training
    elif method == "gbm":
        target = _run_gbm_training
    else:
        target = _run_lstm_training
    t = threading.Thread(target=target, daemon=True, name=f"train-{method}")
    t.start()

    # Give the thread a moment to flip to "training" before returning.
    import time
    time.sleep(0.05)

    with _LOCK:
        return MethodTrainStatus(**_train_status[method])


@router.get("/status")
def get_status() -> AllMethodStatus:
    """Return training status for all three methods."""
    rule_based_status = MethodTrainStatus(
        status="ready",
        progress=1.0,
        message="No training needed",
        metric_label="N/A",
        metric_value=None,
        error=None,
        updated_at=None,
    )
    with _LOCK:
        rf_s = MethodTrainStatus(**_train_status["rf"])
        gbm_s = MethodTrainStatus(**_train_status["gbm"])
        lstm_s = MethodTrainStatus(**_train_status["lstm"])

    return AllMethodStatus(
        rule_based=rule_based_status,
        rf=rf_s,
        gbm=gbm_s,
        lstm=lstm_s,
    )


# ---------------------------------------------------------------------------
# Live movers (Upstox-first) — same ranking as Live Analysis top-movers ladder
# ---------------------------------------------------------------------------
_AVG_VOLUME_WINDOW_DAYS = 20


def _baseline_prev_close_avg_vol(db: Session, symbols: List[str]) -> Dict[str, Tuple[float, int]]:
    """Map symbol -> (prior close, 20d avg daily volume) from `candles`."""
    out: Dict[str, Tuple[float, int]] = {}
    for sym in symbols:
        rows = list(
            db.scalars(
                select(Candle)
                .where(Candle.symbol == sym)
                .order_by(desc(Candle.date))
                .limit(_AVG_VOLUME_WINDOW_DAYS)
            )
        )
        if not rows:
            continue
        prev_close = float(rows[0].close)
        if len(rows) >= 2:
            avg_vol = int(sum(float(r.volume) for r in rows[1:]) / max(len(rows) - 1, 1))
        else:
            avg_vol = int(rows[0].volume)
        out[sym] = (prev_close, avg_vol)
    return out


def _fetch_quotes_nifty50(symbols: List[str]) -> Tuple[Dict[str, float], Dict[str, int], Dict[str, float], str]:
    """Upstox batch first; empty => yfinance LTPs only (no volume / prev from feed)."""
    if upstox_client.is_configured():
        quotes = upstox_client.fetch_quotes_batch(symbols)
        if quotes:
            return (
                {s: q.last_price for s, q in quotes.items()},
                {s: q.volume for s, q in quotes.items()},
                {s: q.close_prev for s, q in quotes.items() if q.close_prev > 0},
                "upstox",
            )
    ltps = live_quotes.fetch_live_prices(symbols)
    return ltps, {}, {}, "yfinance"


@router.get("/live-movers")
def get_live_movers(k: int = 15) -> LiveMoversOut:
    """Today's Nifty 50 intraday movers: same score as `live_analysis.movers.rank_top_k`.

    Prices: Upstox when `UPSTOX_ACCESS_TOKEN` is valid; else delayed yfinance LTPs.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    name_map = {m["symbol"]: m["name"] for m in stock_meta()}
    symbols = all_symbols()

    with session_scope() as db:
        baseline = _baseline_prev_close_avg_vol(db, symbols)

    ltps, volumes, prev_closes_feed, source = _fetch_quotes_nifty50(symbols)

    inputs: List[MoverInput] = []
    for sym in symbols:
        last = ltps.get(sym)
        if not last or last <= 0:
            continue
        prev_close, avg_vol = baseline.get(sym, (0.0, 0))
        prev_close = prev_closes_feed.get(sym, prev_close) or prev_close
        if prev_close <= 0:
            continue
        inputs.append(
            MoverInput(
                symbol=sym,
                last_price=float(last),
                prev_close=float(prev_close),
                volume=int(volumes.get(sym, 0)),
                avg_volume=max(avg_vol, 1),
            )
        )

    ranked = rank_top_k(inputs, k=max(1, min(k, 50)))

    movers = [
        LiveMoverRow(
            rank=m.rank,
            symbol=m.symbol,
            name=name_map.get(m.symbol),
            last_price=m.last_price,
            pct_change=m.pct_change,
            rvol=m.rvol,
            score=m.score,
        )
        for m in ranked
    ]

    return LiveMoversOut(
        movers=movers,
        source=source,
        fetched_at=fetched_at,
        disclaimer=(
            "Research and decision-support only. Not financial advice. "
            "Live mover rank uses intraday quotes (Upstox when configured); "
            "method columns use prior-day EOHLCV indicators — not accuracy comparison."
        ),
    )


@router.post("/run")
def run_analysis(
    method: Literal["rule_based", "rf", "gbm", "lstm"],
) -> MethodRunResult:
    """Run signal analysis on all cached Nifty-50 symbols.

    Returns the top-15 MethodSignalCard entries sorted by confidence.
    """
    ran_at = datetime.now(timezone.utc).isoformat()
    name_map = {m["symbol"]: m["name"] for m in stock_meta()}

    if method == "rule_based":
        cards = _run_rule_based(name_map)
    elif method == "rf":
        if not ml_rf.is_ready():
            raise HTTPException(
                status_code=400,
                detail="Random Forest model not trained yet — click Train first.",
            )
        cards = ml_rf.infer(name_map=name_map, top_k=15)
    elif method == "gbm":
        if not ml_gbm.is_ready():
            raise HTTPException(
                status_code=400,
                detail="GBM model not trained yet — click Train first.",
            )
        cards = ml_gbm.infer(name_map=name_map, top_k=15)
    else:  # lstm
        if not ml_lstm.is_ready():
            raise HTTPException(
                status_code=400,
                detail="LSTM model not trained yet — click Train first.",
            )
        cards = ml_lstm.infer(name_map=name_map, top_k=15)

    return MethodRunResult(
        method=method,
        signals=[MethodSignalCard(**c) for c in cards],
        ran_at=ran_at,
        disclaimer="Research and decision-support only. Not financial advice.",
    )


# ---------------------------------------------------------------------------
# Rule-based helper (reuses existing signals.py pipeline)
# ---------------------------------------------------------------------------
def _run_rule_based(name_map: Dict[str, str]) -> List[dict]:
    """Run the existing rule-based screener on all cached symbols and convert
    the highest-confidence signal per symbol into a MethodSignalCard dict."""
    from ..analysis.indicators import compute_all
    from ..analysis.signals import evaluate_symbol
    from ..data import csv_store

    symbols = csv_store.list_cached_symbols()
    best_per_symbol: Dict[str, dict] = {}

    for sym in symbols:
        df_raw = csv_store.load(sym)
        if len(df_raw) < 60:
            continue
        try:
            df_enriched = compute_all(df_raw)
            records = evaluate_symbol(sym, df_raw, df_enriched=df_enriched)
        except Exception:
            log.debug("Rule-based eval failed for %s", sym, exc_info=True)
            continue

        for rec in records:
            prev = best_per_symbol.get(sym)
            if prev is None or rec.confidence > prev["confidence"]:
                close_val = float(df_raw.iloc[-1]["close"]) if not df_raw.empty else 0.0
                # Directional mapping: avoidance categories get NEUTRAL/SHORT.
                avoid_cats = {"OVERBOUGHT_AVOID", "WEAK_AVOID", "HIGH_RISK"}
                short_cats = {"WEAK_AVOID"}
                direction = (
                    "SHORT" if rec.category in short_cats
                    else "NEUTRAL" if rec.category in avoid_cats
                    else "LONG"
                )
                best_per_symbol[sym] = {
                    "symbol": sym,
                    "name": name_map.get(sym),
                    "confidence": round(rec.confidence, 3),
                    "direction": direction,
                    "category": rec.category,
                    "regime": rec.regime,
                    "close": close_val,
                    "top_factors": rec.reasons[:5],
                }

    cards = sorted(best_per_symbol.values(), key=lambda c: -c["confidence"])
    return cards[:15]
