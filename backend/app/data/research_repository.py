"""Persistence for immutable research runs and their briefing context."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.agent_orm import DailyBriefing, ResearchRun


def latest_context(db: Session) -> dict:
    row = db.scalar(select(DailyBriefing).order_by(DailyBriefing.run_at.desc()).limit(1))
    if row is None:
        return {"available": False}
    return {"available": True, "observed_at": row.run_at.isoformat() + "Z",
            "regime": row.regime, "events": (row.upcoming_events_json or [])[:20]}


def save_run(db: Session, result: dict) -> dict:
    row = ResearchRun(asset_class=result["asset_class"], horizon=result["horizon"], result_json=result)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {**result, "id": row.id}


def recent_runs(db: Session, asset_class: str, horizon: str, limit: int = 10) -> list[dict]:
    rows = db.scalars(select(ResearchRun).where(
        ResearchRun.asset_class == asset_class, ResearchRun.horizon == horizon,
    ).order_by(ResearchRun.id.desc()).limit(limit))
    return [{**row.result_json, "id": row.id} for row in rows]
