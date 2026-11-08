"""system_config · 运行期配置表（docs/03 §2.16）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200))
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
