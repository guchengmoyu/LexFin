"""知识库服务（docs/06 §5.3）。统计数字直接查库，保证与验收 SQL 一致。"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import CATEGORY_SUB, ErrorCode
from app.core.exceptions import BizError
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_point import KnowledgePoint
from app.models.user import User
from app.utils.time import now


class KbService:
    def list(self, db: Session) -> List[dict]:
        kbs = db.scalars(select(KnowledgeBase).where(KnowledgeBase.status == 1)).all()
        return [self._to_dict(db, kb) for kb in kbs]

    def get(self, db: Session, kb_id: int) -> dict:
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise BizError(ErrorCode.NOT_FOUND, "知识库不存在")
        return self._to_dict(db, kb)

    def create(self, db: Session, payload: dict, user: User) -> dict:
        exists = db.scalar(select(KnowledgeBase).where(KnowledgeBase.code == payload["code"]))
        if exists:
            raise BizError(ErrorCode.CONFLICT, "知识库编码已存在")
        kb = KnowledgeBase(
            code=payload["code"],
            name=payload["name"],
            category=payload["category"],
            description=payload.get("description"),
            status=1,
            created_by=user.id,
            created_at=now(),
            updated_at=now(),
        )
        db.add(kb)
        db.commit()
        db.refresh(kb)
        return self._to_dict(db, kb)

    def update(self, db: Session, kb_id: int, payload: dict) -> dict:
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise BizError(ErrorCode.NOT_FOUND, "知识库不存在")
        for key in ("name", "description", "status"):
            if payload.get(key) is not None:
                setattr(kb, key, payload[key])
        kb.updated_at = now()
        db.commit()
        return self._to_dict(db, kb)

    def delete(self, db: Session, kb_id: int) -> dict:
        """软删除（status=0）；级联清理由 DocumentService / KnowledgePointService 负责。"""
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise BizError(ErrorCode.NOT_FOUND, "知识库不存在")
        kb.status = 0
        kb.updated_at = now()
        db.commit()
        return {"kb_id": kb_id, "deleted": True}

    def stats(self, db: Session, kb_id: int) -> dict:
        """AC-01（知识点 ≥1000）与知识点分布验收的直接数据来源（docs/06 §5.3）。"""
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise BizError(ErrorCode.NOT_FOUND, "知识库不存在")

        doc_count = db.scalar(
            select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
        )
        ready_doc_count = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.kb_id == kb_id, Document.status == "ready")
        )
        error_doc_count = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.kb_id == kb_id, Document.status == "error")
        )
        chunk_count = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
        )
        kp_total = db.scalar(
            select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.kb_id == kb_id)
        )
        published = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.kb_id == kb_id, KnowledgePoint.status == "published")
        )
        verified = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.kb_id == kb_id, KnowledgePoint.verify_status == "passed")
        )
        verified_total = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(
                KnowledgePoint.kb_id == kb_id,
                KnowledgePoint.verify_status.in_(["passed", "doubted", "rejected"]),
            )
        ) or 0

        sub_rows = db.execute(
            select(KnowledgePoint.sub_category, func.count())
            .where(KnowledgePoint.kb_id == kb_id, KnowledgePoint.sub_category.is_not(None))
            .group_by(KnowledgePoint.sub_category)
        ).all()
        timeliness_rows = db.execute(
            select(DocumentChunk.id)  # 占位，改为按切片统计时效需要 join
            .where(DocumentChunk.kb_id == kb_id)
            .limit(0)
        ).all()
        timeliness_dist = db.execute(
            select(Document.timeliness, func.count())
            .where(Document.kb_id == kb_id)
            .group_by(Document.timeliness)
        ).all()
        top_docs = db.execute(
            select(Document.id, Document.title, Document.chunk_count)
            .where(Document.kb_id == kb_id)
            .order_by(Document.chunk_count.desc())
            .limit(5)
        ).all()

        return {
            "kb_id": kb.id,
            "name": kb.name,
            "doc_count": int(doc_count or 0),
            "ready_doc_count": int(ready_doc_count or 0),
            "error_doc_count": int(error_doc_count or 0),
            "chunk_count": int(chunk_count or 0),
            "kp_count": int(kp_total or 0),
            "published_kp_count": int(published or 0),
            "verified_kp_count": int(verified or 0),
            "verify_pass_rate": round(verified / verified_total, 3) if verified_total else None,
            "sub_category_distribution": [
                {"sub_category": r[0], "count": int(r[1])} for r in sub_rows
            ],
            "timeliness_distribution": [
                {"timeliness": r[0], "count": int(r[1])} for r in timeliness_dist
            ],
            "top_documents": [
                {"id": int(r[0]), "title": r[1], "chunk_count": int(r[2] or 0)} for r in top_docs
            ],
        }

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def refresh_counters(db: Session, kb_id: int) -> None:
        """冗余统计异步刷新（docs/03 §2.2）。"""
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            return
        kb.doc_count = db.scalar(
            select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
        ) or 0
        kb.chunk_count = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
        ) or 0
        kb.kp_count = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.kb_id == kb_id, KnowledgePoint.status == "published")
        ) or 0
        kb.updated_at = now()
        db.commit()

    @staticmethod
    def _to_dict(db: Session, kb: KnowledgeBase) -> dict:
        doc_count = db.scalar(
            select(func.count()).select_from(Document).where(Document.kb_id == kb.id)
        )
        chunk_count = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.kb_id == kb.id)
        )
        kp_count = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.kb_id == kb.id, KnowledgePoint.status == "published")
        )
        return {
            "id": kb.id,
            "code": kb.code,
            "name": kb.name,
            "category": kb.category,
            "description": kb.description,
            "doc_count": int(doc_count or 0),
            "chunk_count": int(chunk_count or 0),
            "kp_count": int(kp_count or 0),
            "status": kb.status,
            "created_at": kb.created_at.strftime("%Y-%m-%d %H:%M:%S") if kb.created_at else None,
        }


kb_service = KbService()
