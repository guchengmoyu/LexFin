"""document_chunk · 文档切片表（docs/03 §2.4）。

content 为「带元数据前缀」的切片正文（直接影响检索召回）：
【{doc_title}｜{doc_no}｜{chapter_no} {article_no}】\\n{raw_content}
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_no: Mapped[Optional[str]] = mapped_column(String(50))
    article_no: Mapped[Optional[str]] = mapped_column(String(50))
    page_start: Mapped[Optional[int]] = mapped_column(Integer)
    page_end: Mapped[Optional[int]] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    source_type: Mapped[str] = mapped_column(String(16), default="text")
    embedding_status: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
