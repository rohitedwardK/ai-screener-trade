"""Live verification orchestrator for index strike recommendations.

Bridges the pure verifier (`analysis/live_strike_verifier`) with the rest of
the stack:

    repository.active_recommendations  ─┐
    upstox_options.fetch_upstox_chain   ├──► verifier.evaluate ──► repo.update
    upstox_client.fetch_quotes (LTP)    │              │
    live_quotes.fetch_live_prices       │              │
    parent IndexSignal (spot SL gate) ──┘              │
                                                        ▼
                                       index_strike_recommendations.status

Runs every 5 min during market hours via `core/scheduler.py`. Idempotent and
exception-safe: a single bad recommendation never blocks the rest of the run.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..analysis import live_strike_verifier as lsv
from ..core.index_universe import get_index
from ..data import index_repository as idx_repo
from ..data import live_quotes, upstox_client, upstox_options
from ..db import session_scope
from ..models.index_orm import IndexSignal, IndexStrikeRecommendation

log = logging.getLogger(__name__)


@dataclass
class StrikeVerificationResult:
    """Summary returned by `run_strike_verification` and surfaced via API."""
    started_at: datetime
    finished_at: datetime
    recommendations_evaluated: int
    rows_updated: int
    by_status: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def _resolve_premiums_via_upstox(
    rows: List[IndexStrikeRecommendation],
) -> Dict[int, float]:
    """Best-effort Upstox lookup: rec.id → live premium for the long leg.

    Why the long leg: for SINGLE_LEG it's the only leg; for DEBIT_SPREAD
    we use the bought leg's premium minus the sold leg's premium = current
    net debit. We need both legs to compute that, so for spreads we collect
    both, look them up in one batch, then reconstruct net debit.

    Returns an empty dict when Upstox is not configured / dead-token / 401.
    Caller falls back to refreshing the chain via `upstox_options`.
    """
    if not rows or not upstox_client.is_configured():
        return {}

    # Map rec_id → list of (instrument_key, side) so we can both fetch in one
    # batch and reconstruct net debit afterwards.
    legs_by_rec: Dict[int, List[Tuple[str, str]]] = {}
    keys: set[str] = set()
    for r in rows:
        legs = r.legs_json or []
        leg_keys: List[Tuple[str, str]] = []
        for leg in legs:
            ikey = leg.get("instrument_key")
            if not isinstance(ikey, str) or not ikey:
                continue
            leg_keys.append((ikey, str(leg.get("side", "BUY"))))
            keys.add(ikey)
        if leg_keys:
            legs_by_rec[int(r.id)] = leg_keys

    if not keys:
        return {}

    try:
        ltps = upstox_client.fetch_quotes_by_instrument_keys(sorted(keys))
    except Exception:  # noqa: BLE001 - one bad batch must not block the run
        log.warning("Upstox option-LTP batch failed", exc_info=True)
        return {}

    out: Dict[int, float] = {}
    for rec_id, leg_list in legs_by_rec.items():
        net = 0.0
        ok = True
        for ikey, side in leg_list:
            ltp = ltps.get(ikey)
            if ltp is None:
                ok = False
                break
            net += ltp if side == "BUY" else -ltp
        if ok and net > 0:
            out[rec_id] = round(net, 2)
    return out


def _resolve_premiums_via_chain(
    rows: List[IndexStrikeRecommendation],
    upstox_premiums: Dict[int, float],
) -> Dict[int, float]:
    """Re-fetch the option chain (Upstox primary, NSE/yfinance fallback) for
    any (code, expiry) we still need a premium for, then look up legs by strike.

    This is the slow path — used when Upstox direct LTP didn't return for a
    leg or when the recommendation has no instrument_key persisted (NSE /
    yfinance source). One chain fetch per (code, expiry) regardless of how
    many recommendations share it."""
    todo = [r for r in rows if int(r.id) not in upstox_premiums]
    if not todo:
        return {}

    # Group by (code, expiry) so we fetch each chain once per tick.
    by_chain: Dict[Tuple[str, date], List[IndexStrikeRecommendation]] = defaultdict(list)
    for r in todo:
        by_chain[(r.code, r.expiry)].append(r)

    out: Dict[int, float] = {}
    for (code, expiry), group in by_chain.items():
        try:
            result = upstox_options.fetch_upstox_option_chain(code, expiry)
        except Exception:  # noqa: BLE001
            log.warning("upstox chain fetch failed for %s %s", code, expiry, exc_info=True)
            result = None
        if result is None:
            continue
        payload, _keys = result
        # Build a strike → row index for O(1) leg lookups.
        strikes = {r.strike: r for r in payload.rows}
        for rec in group:
            net = 0.0
            ok = True
            for leg in rec.legs_json or []:
                strike = leg.get("strike")
                option_type = leg.get("option_type")
                side = str(leg.get("side", "BUY"))
                if strike is None or option_type not in ("CE", "PE"):
                    ok = False
                    break
                row = strikes.get(float(strike))
                if row is None:
                    ok = False
                    break
                ltp = row.ce_ltp if option_type == "CE" else row.pe_ltp
                if ltp is None or ltp <= 0:
                    ok = False
                    break
                net += float(ltp) if side == "BUY" else -float(ltp)
            if ok and net > 0:
                out[int(rec.id)] = round(net, 2)
    return out


def _spot_sl_violated(sig: Optional[IndexSignal], spot_ltp: Optional[float]) -> bool:
    """True when live spot has crossed the parent signal's stop-loss."""
    if sig is None or sig.stop_loss is None or spot_ltp is None:
        return False
    if sig.direction == "LONG":
        return spot_ltp <= float(sig.stop_loss)
    if sig.direction == "SHORT":
        return spot_ltp >= float(sig.stop_loss)
    return False


def _load_parent_signals(
    db: Session, rows: List[IndexStrikeRecommendation],
) -> Dict[int, IndexSignal]:
    """One bulk lookup for all parent signals so we don't N+1 the DB."""
    if not rows:
        return {}
    ids = sorted({int(r.signal_id) for r in rows})
    out: Dict[int, IndexSignal] = {}
    for sig_id in ids:
        sig = db.get(IndexSignal, sig_id)
        if sig is not None:
            out[sig_id] = sig
    return out


def run_strike_verification(
    *, db: Optional[Session] = None,
) -> StrikeVerificationResult:
    """Execute one verification pass over ACTIVE strike recommendations.

    Idempotent. Safe to call from the scheduler, the live API endpoint, and
    tests alike.
    """
    started = datetime.utcnow()
    by_status: Dict[str, int] = {s: 0 for s in lsv.ALL_STATUSES}
    rows_updated = 0
    errors: List[str] = []

    own_session = db is None
    db_ctx = session_scope() if own_session else None
    try:
        if db_ctx is not None:
            db = db_ctx.__enter__()
        assert db is not None

        rows = idx_repo.active_recommendations(db)
        if not rows:
            return StrikeVerificationResult(
                started_at=started,
                finished_at=datetime.utcnow(),
                recommendations_evaluated=0,
                rows_updated=0,
                by_status=by_status,
                errors=[],
            )

        # 1. Resolve premiums in two passes: fast Upstox direct, then chain.
        ups_premiums = _resolve_premiums_via_upstox(rows)
        chain_premiums = _resolve_premiums_via_chain(rows, ups_premiums)
        all_premiums: Dict[int, float] = dict(ups_premiums)
        all_premiums.update(chain_premiums)

        # 2. Bulk-fetch parent signals + live spot LTPs.
        parents = _load_parent_signals(db, rows)
        spot_symbols = sorted({sig.symbol for sig in parents.values()})
        spot_ltps = (
            live_quotes.fetch_live_prices(spot_symbols) if spot_symbols else {}
        )

        # 3. Per-row evaluation.
        today_d = date.today()
        run_at = datetime.utcnow()
        for row in rows:
            try:
                persisted = lsv.PersistedRecommendation(
                    id=int(row.id),
                    expiry=row.expiry,
                    entry_premium=float(row.entry_premium),
                    sl_premium=float(row.sl_premium),
                    t1_premium=float(row.t1_premium),
                    t2_premium=float(row.t2_premium),
                    current_status=str(row.status),
                )
                parent = parents.get(int(row.signal_id))
                spot = spot_ltps.get(parent.symbol) if parent else None
                violated = _spot_sl_violated(parent, spot)
                current_premium = all_premiums.get(int(row.id))
                outcome = lsv.evaluate(
                    persisted,
                    current_premium=current_premium,
                    today=today_d,
                    spot_sl_violated=violated,
                )
                idx_repo.update_recommendation_status(
                    db,
                    recommendation_id=outcome.recommendation_id,
                    status=outcome.status,
                    last_premium=outcome.last_premium,
                    last_checked_at=run_at,
                )
                by_status[outcome.status] = by_status.get(outcome.status, 0) + 1
                rows_updated += 1
            except Exception as exc:  # noqa: BLE001 - one bad row must not block the run
                log.exception("strike verification failed for rec %s", row.id)
                errors.append(f"rec#{row.id}: {exc}")

        if own_session:
            db.commit()
    finally:
        if db_ctx is not None:
            db_ctx.__exit__(None, None, None)

    finished = datetime.utcnow()
    log.info(
        "live strike verification: rows=%d updated=%d active=%d t1=%d t2=%d "
        "stop=%d invalidated=%d expired=%d errors=%d",
        len(rows) if 'rows' in locals() else 0,
        rows_updated,
        by_status.get(lsv.STATUS_ACTIVE, 0),
        by_status.get(lsv.STATUS_T1_HIT, 0),
        by_status.get(lsv.STATUS_T2_HIT, 0),
        by_status.get(lsv.STATUS_STOP_HIT, 0),
        by_status.get(lsv.STATUS_INVALIDATED, 0),
        by_status.get(lsv.STATUS_EXPIRED, 0),
        len(errors),
    )
    return StrikeVerificationResult(
        started_at=started,
        finished_at=finished,
        recommendations_evaluated=rows_updated,
        rows_updated=rows_updated,
        by_status=by_status,
        errors=errors,
    )


# Suppress the unused-import warning when get_index isn't called yet — kept
# importable so future callers (e.g. an admin endpoint) don't add it twice.
_ = get_index


__all__ = [
    "StrikeVerificationResult",
    "run_strike_verification",
]
