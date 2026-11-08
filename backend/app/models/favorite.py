"""favorite · 收藏表（docs/03 §2.11）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Favorite(Base):
    __tablename__ = "favorite"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uk_user_msg"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    question: Mapped[Optional[str]] = mapped_column(String(500))
    answer_digest: Mapped[Optional[str]] = mapped_column(String(500))
    note: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
