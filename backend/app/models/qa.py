"""qa_session / qa_message / qa_citation（docs/03 §2.8~2.10）。

qa_citation 对 document/chunk/kp 为弱引用且字段冗余快照，
即使原文档被删除，历史问答的溯源信息仍可完整展示。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.mysql import JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QASession(Base):
    __tablename__ = "qa_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(200))
    kb_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QAMessage(Base):
    __tablename__ = "qa_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    answer_type: Mapped[Optional[str]] = mapped_column(String(16))
    retrieval_mode: Mapped[Optional[str]] = mapped_column(String(16))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    latency_detail: Mapped[Optional[dict]] = mapped_column(JSON)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(16))
    model_name: Mapped[Optional[str]] = mapped_column(String(50))
    token_usage: Mapped[Optional[dict]] = mapped_column(JSON)
    kb_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QACitation(Base):
    __tablename__ = "qa_citation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cite_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    knowledge_point_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    document_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    doc_title: Mapped[Optional[str]] = mapped_column(String(300))
    doc_no: Mapped[Optional[str]] = mapped_column(String(100))
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(100))
    article_no: Mapped[Optional[str]] = mapped_column(String(50))
    page_no: Mapped[Optional[int]] = mapped_column(Integer)
    timeliness: Mapped[Optional[str]] = mapped_column(String(16))
    snippet: Mapped[Optional[str]] = mapped_column(String(1000))
    score: Mapped[Optional[float]] = mapped_column(Numeric(6, 5))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
