from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.notification_orm import Notification

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    symbol: Optional[str]
    title: str
    message: str
    event_type: str
    severity: str
    status: str
    route: Optional[str]


@router.get("", response_model=List[NotificationOut])
def list_notifications(limit: int = 30, db: Session = Depends(get_db)):
    return list(db.scalars(select(Notification).order_by(desc(Notification.created_at)).limit(min(limit, 100))).all())


@router.patch("/{notification_id}", response_model=NotificationOut)
def mark_notification(notification_id: int, db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if row is None:
        raise HTTPException(404, "Notification not found")
    row.status = "READ"
    db.commit()
    db.refresh(row)
    return row
