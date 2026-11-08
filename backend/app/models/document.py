"""document · 制度文档表（docs/03 §2.3）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("kb_id", "file_md5", name="uk_kb_md5"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_no: Mapped[Optional[str]] = mapped_column(String(100))
    doc_type: Mapped[str] = mapped_column(String(20), default="regulation")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(100))
    publish_date: Mapped[Optional[date]] = mapped_column(Date)
    effective_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    timeliness: Mapped[str] = mapped_column(String(16), default="unknown")
    superseded_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    is_latest: Mapped[int] = mapped_column(Integer, default=1)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_ext: Mapped[str] = mapped_column(String(16), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    file_md5: Mapped[str] = mapped_column(String(32), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_method: Mapped[Optional[str]] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(String(500))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    keywords: Mapped[Optional[str]] = mapped_column(String(500))
    uploaded_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
