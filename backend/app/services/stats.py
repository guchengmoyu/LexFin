"""统计服务（docs/06 §5.2 /stats/overview）：首页统计与系统配置字典。"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    CATEGORY_LABELS,
    CATEGORY_SUB,
    DOC_TYPE_LABELS,
    RETRIEVAL_MODE_LABELS,
    TIMELINESS_LABELS,
)
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_point import KnowledgePoint
from app.models.qa import QAMessage
from app.models.task import QAReview


class StatsService:
    def overview(self, db: Session) -> dict:
        kb_count = db.scalar(
            select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.status == 1)
        ) or 0
        document_count = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.status.in_(["ready", "embedding", "parsing", "pending"]))
        ) or 0
        chunk_count = db.scalar(select(func.count()).select_from(DocumentChunk)) or 0
        kp_count = db.scalar(select(func.count()).select_from(KnowledgePoint)) or 0
        published = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.status == "published")
        ) or 0
        verified = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.verify_status == "passed")
        ) or 0
        judged = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.verify_status.in_(["passed", "doubted", "rejected"]))
        ) or 0

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        qa_total = db.scalar(
            select(func.count()).select_from(QAMessage).where(QAMessage.role == "assistant")
        ) or 0
        qa_today = db.scalar(
            select(func.count())
            .select_from(QAMessage)
            .where(QAMessage.role == "assistant", QAMessage.created_at >= today)
        ) or 0
        avg_latency = db.scalar(
            select(func.avg(QAMessage.latency_ms)).where(QAMessage.role == "assistant")
        )
        avg_confidence = db.scalar(
            select(func.avg(QAMessage.confidence)).where(QAMessage.role == "assistant")
        )

        category_rows = db.execute(
            select(KnowledgePoint.category, func.count())
            .where(KnowledgePoint.status == "published")
            .group_by(KnowledgePoint.category)
        ).all()
        doc_category_rows = db.execute(
            select(Document.category, func.count())
            .where(Document.status == "ready")
            .group_by(Document.category)
        ).all()
        docs_by_cat = {r[0]: int(r[1]) for r in doc_category_rows}

        recent_docs = db.scalars(
            select(Document)
            .where(Document.status != "archived")
            .order_by(Document.created_at.desc())
            .limit(5)
        ).all()

        return {
            "kb_count": int(kb_count),
            "document_count": int(document_count),
            "chunk_count": int(chunk_count),
            "knowledge_point_count": int(kp_count),
            "published_kp_count": int(published),
            "verified_kp_count": int(verified),
            "verify_pass_rate": round(verified / judged, 3) if judged else None,
            "qa_total": int(qa_total),
            "qa_today": int(qa_today),
            "avg_latency_ms": int(avg_latency) if avg_latency else None,
            "avg_confidence": round(float(avg_confidence), 3) if avg_confidence else None,
            "category_distribution": [
                {"category": r[0], "docs": docs_by_cat.get(r[0], 0), "kps": int(r[1])}
                for r in category_rows
            ],
            "recent_documents": [
                {"id": d.id, "title": d.title, "status": d.status,
                 "created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if d.created_at else None}
                for d in recent_docs
            ],
        }

    @staticmethod
    def system_config() -> dict:
        """前端所有下拉选项必须来自此接口（docs/06 §5.2）。"""
        return {
            "categories": [
                {
                    "value": key,
                    "label": CATEGORY_LABELS[key],
                    "sub_categories": CATEGORY_SUB[key],
                }
                for key in ("banking", "securities", "insurance")
            ],
            "doc_types": [
                {"value": k, "label": v} for k, v in DOC_TYPE_LABELS.items()
            ],
            "timeliness": [
                {"value": k, "label": v} for k, v in TIMELINESS_LABELS.items()
            ],
            "retrieval_modes": [
                {"value": k, "label": v} for k, v in RETRIEVAL_MODE_LABELS.items()
            ],
            "allowed_extensions": settings.allowed_extension_list,
            "max_file_size_mb": settings.max_file_size_mb,
            "features": {
                "multi_turn": settings.multi_turn_enabled,
                "rerank": settings.rerank_enabled,
                "knowledge_verify": True,
                "favorite": True,
            },
        }


stats_service = StatsService()
