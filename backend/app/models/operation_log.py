"""operation_log · 操作日志表（docs/03 §2.15，P2 预留）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OperationLog(Base):
    __tablename__ = "operation_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(30))
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    detail: Mapped[Optional[dict]] = mapped_column(JSON)
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    request_id: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
