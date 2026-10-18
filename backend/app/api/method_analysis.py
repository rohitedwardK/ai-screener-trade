"""Method Analysis API — Rule-Based baseline and Random Forest.

POST /method-analysis/train?method=rf
GET  /method-analysis/status
POST /method-analysis/run?method=rule_based|rf
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..analysis import ml_rf
from ..core import method_analysis as method_service
from ..core import trade_quality
from ..core.universe import stock_meta

log = logging.getLogger(__name__)
router = APIRouter(prefix="/method-analysis", tags=["method-analysis"])


class QualityTrainingStatus(BaseModel):
    status: str
    message: str
    model: Optional[dict] = None
    target: str
    disclaimer: str
    data: Optional[dict] = None


@router.get("/quality/status", response_model=QualityTrainingStatus)
def quality_status() -> dict:
    """Quality training state and chronological holdout AUC/Brier/base-rate metrics."""
    return trade_quality.status()


@router.post("/quality/train", response_model=QualityTrainingStatus)
def train_quality(source: Literal["archive", "historical"] = "archive") -> dict:
    """Train calibrated RF on recorded observations or reconstructed weekly EOD setups.

    Historical mode uses up to five years of cached prices for the configured
    stock universe, recomputing indicators on each historical slice. It does not
    create live observations. Results retain source and survivorship limitations.

    Target: target_1 touched before stop/invalidation in the next five complete
    sessions, excluding the observation day. Both touched on one bar counts as
    failure. No fills or trading returns are assumed. Requires 100 mature samples,
    30 observation dates and both outcomes in purged train/calibration/test sets.
    Scores are withheld unless holdout Brier beats the training base rate.
    """
    return trade_quality.start_training(source)

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
}

# Pre-populate "ready" if model artefacts already exist on disk.
if ml_rf.is_ready():
    _train_status["rf"]["status"] = "ready"


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
            metric_label="Held-out test AUC",
            metric_value=round(result["test_auc"], 3) if result["test_auc"] is not None else None,
        )
        log.info("Random Forest training complete — held-out test AUC %s", result["test_auc"])
    except Exception as exc:
        log.exception("Random Forest training failed")
        _set_status("rf", status="error", error=str(exc), message="Training failed")


# ---------------------------------------------------------------------------
@router.post("/train")
def start_training(method: Literal["rf"]) -> MethodTrainStatus:
    """Start training the selected model in a background thread."""
    with _LOCK:
        current = _train_status[method]["status"]

    if current == "training":
        with _LOCK:
            return MethodTrainStatus(**_train_status[method])

    t = threading.Thread(target=_run_rf_training, daemon=True, name=f"train-{method}")
    t.start()

    # Give the thread a moment to flip to "training" before returning.
    import time
    time.sleep(0.05)

    with _LOCK:
        return MethodTrainStatus(**_train_status[method])


@router.get("/status")
def get_status() -> AllMethodStatus:
    """Return Random Forest training status and rule-based baseline readiness."""
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

    return AllMethodStatus(
        rule_based=rule_based_status,
        rf=rf_s,
    )


# ---------------------------------------------------------------------------
# Live movers (Upstox-first) — same ranking as Live Analysis top-movers ladder
# ---------------------------------------------------------------------------
@router.get("/live-movers")
def get_live_movers(k: int = 15) -> LiveMoversOut:
    """Today's Nifty 50 intraday movers: same score as `live_analysis.movers.rank_top_k`.

    Prices: Upstox when `UPSTOX_ACCESS_TOKEN` is valid; else delayed yfinance LTPs.
    """
    result = method_service.get_live_movers(k=k)

    return LiveMoversOut(
        movers=[LiveMoverRow(**row) for row in result["movers"]],
        source=str(result["source"]),
        fetched_at=str(result["fetched_at"]),
        disclaimer=(
            "Research and decision-support only. Not financial advice. "
            "Live mover rank uses intraday quotes (Upstox when configured); "
            "method columns use prior-day EOHLCV indicators — not accuracy comparison."
        ),
    )


@router.post("/run")
def run_analysis(
    method: Literal["rule_based", "rf"],
) -> MethodRunResult:
    """Run signal analysis on all cached Nifty-50 symbols.

    Returns the top-15 MethodSignalCard entries sorted by confidence.
    """
    ran_at = datetime.now(timezone.utc).isoformat()
    name_map = {m["symbol"]: m["name"] for m in stock_meta()}

    if method == "rule_based":
        cards = method_service.run_rule_based(name_map)
    elif method == "rf":
        if not ml_rf.is_ready():
            raise HTTPException(
                status_code=400,
                detail="Random Forest model not trained yet — click Train first.",
            )
        cards = ml_rf.infer(name_map=name_map, top_k=15)

    return MethodRunResult(
        method=method,
        signals=[MethodSignalCard(**c) for c in cards],
        ran_at=ran_at,
        disclaimer="Research and decision-support only. Not financial advice.",
    )


# ---------------------------------------------------------------------------
# Rule-based helper (reuses existing signals.py pipeline)
# ---------------------------------------------------------------------------
