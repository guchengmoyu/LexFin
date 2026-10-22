"""qa_feedback · 答案反馈表（docs/03 §2.12）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QAFeedback(Base):
    __tablename__ = "qa_feedback"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uk_user_msg"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(50))
    comment: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16), default="open")
    handled_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    handled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    handle_note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
