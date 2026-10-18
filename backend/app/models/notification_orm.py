from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from .orm import Base


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    symbol = Column(String, nullable=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    event_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="INFO")
    status = Column(String, nullable=False, default="UNREAD")
    route = Column(String, nullable=True)
    __table_args__ = (Index("ix_notifications_created_at", "created_at"),)
