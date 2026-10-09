"""knowledge_point / knowledge_point_source / knowledge_point_relation（docs/03 §2.5~2.7）。

knowledge_point 是本项目的核心资产与验收指标载体（published ≥ 1000）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgePoint(Base):
    __tablename__ = "knowledge_point"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    sub_category: Mapped[Optional[str]] = mapped_column(String(50))
    doc_no: Mapped[Optional[str]] = mapped_column(String(100))
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(100))
    article_no: Mapped[Optional[str]] = mapped_column(String(50))
    effective_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)
    timeliness: Mapped[str] = mapped_column(String(16), default="unknown")
    keywords: Mapped[Optional[str]] = mapped_column(String(500))
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    source_type: Mapped[str] = mapped_column(String(16), default="manual")
    primary_document_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    primary_chunk_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    embedding_status: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    verify_status: Mapped[str] = mapped_column(String(16), default="pending")
    verified_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    verify_comment: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KnowledgePointSource(Base):
    __tablename__ = "knowledge_point_source"
    __table_args__ = (UniqueConstraint("knowledge_point_id", "chunk_id", name="uk_kp_chunk"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_point_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_no: Mapped[Optional[int]] = mapped_column(Integer)
    article_no: Mapped[Optional[str]] = mapped_column(String(50))
    quote_text: Mapped[Optional[str]] = mapped_column(Text)
    is_primary: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KnowledgePointRelation(Base):
    __tablename__ = "knowledge_point_relation"
    __table_args__ = (
        UniqueConstraint("source_kp_id", "target_kp_id", "relation_type", name="uk_rel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_kp_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_kp_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
