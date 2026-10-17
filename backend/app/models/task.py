"""ingest_task · 入库任务表（docs/03 §2.14）与 qa_review · 人工校验记录表（docs/03 §2.13）。

qa_review 是「人工校验准确率 ≥ 85%」验收指标的数据来源；
uk_reviewer_target 支持双人独立标注（Cohen's Kappa）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestTask(Base):
    __tablename__ = "ingest_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    task_type: Mapped[str] = mapped_column(String(20), default="ingest")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage_message: Mapped[Optional[str]] = mapped_column(String(200))
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    done_chunks: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000))
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QAReview(Base):
    __tablename__ = "qa_review"
    __table_args__ = (
        UniqueConstraint("reviewer_id", "target_type", "target_id", name="uk_reviewer_target"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reviewer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_correct: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[Optional[str]] = mapped_column(String(32))
    comment: Mapped[Optional[str]] = mapped_column(String(1000))
    batch_no: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
