"""知识点服务（docs/06 §5.6）。

知识点是本项目核心资产与验收指标载体（published ≥ 1000），
批量导入接口是达成该指标的主要通道。
"""
from __future__ import annotations

import csv
import io
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.constants import (
    CATEGORY_SUB,
    ErrorCode,
    KP_CODE_PREFIX,
    Role,
)
from app.core.exceptions import BizError
from app.core.response import paged as paged_result
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_point import (
    KnowledgePoint,
    KnowledgePointRelation,
    KnowledgePointSource,
)
from app.models.task import QAReview
from app.models.user import User
from app.rag.embedder import encode_query
from app.rag.indexer import build_filter, indexer
from app.utils.time import now

IMPORT_COLUMNS = [
    "title", "content", "category", "sub_category", "doc_no", "issuing_authority",
    "article_no", "effective_date", "expiry_date", "timeliness", "keywords",
    "difficulty", "code", "status",
]
REQUIRED_COLUMNS = ["title", "content", "category"]


class KnowledgePointService:
    # ---------------------------------------------------------------- 查询
    def list(self, db: Session, filters: dict, page: int, size: int) -> dict:
        query = select(KnowledgePoint)
        if filters.get("kb_id"):
            query = query.where(KnowledgePoint.kb_id == filters["kb_id"])
        if filters.get("category"):
            query = query.where(KnowledgePoint.category == filters["category"])
        if filters.get("sub_category"):
            query = query.where(KnowledgePoint.sub_category == filters["sub_category"])
        if filters.get("timeliness"):
            query = query.where(KnowledgePoint.timeliness == filters["timeliness"])
        if filters.get("verify_status"):
            query = query.where(KnowledgePoint.verify_status == filters["verify_status"])
        if filters.get("status"):
            query = query.where(KnowledgePoint.status == filters["status"])
        if filters.get("difficulty"):
            query = query.where(KnowledgePoint.difficulty == filters["difficulty"])
        if filters.get("keyword"):
            like = f"%{filters['keyword']}%"
            query = query.where(
                or_(
                    KnowledgePoint.title.like(like),
                    KnowledgePoint.content.like(like),
                    KnowledgePoint.keywords.like(like),
                )
            )
        if filters.get("has_source") is not None:
            if filters["has_source"]:
                query = query.where(KnowledgePoint.primary_chunk_id.is_not(None))
            else:
                query = query.where(KnowledgePoint.primary_chunk_id.is_(None))

        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(KnowledgePoint.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
        return paged_result(total, page, size, [self.to_dict(kp) for kp in rows])

    def get(self, db: Session, kp_id: int) -> KnowledgePoint:
        kp = db.get(KnowledgePoint, kp_id)
        if kp is None:
            raise BizError(ErrorCode.KNOWLEDGE_POINT_NOT_FOUND, "知识点不存在")
        return kp

    def detail(self, db: Session, kp_id: int) -> dict:
        return self.to_dict(self.get(db, kp_id))

    # ---------------------------------------------------------------- 写入
    def create(self, db: Session, payload: dict, user: User) -> dict:
        kb = db.get(KnowledgeBase, payload["kb_id"])
        if kb is None:
            raise BizError(ErrorCode.NOT_FOUND, "知识库不存在")
        self._check_chunk(db, payload.get("primary_chunk_id"), payload["kb_id"])

        kp = KnowledgePoint(
            kb_id=payload["kb_id"],
            title=payload["title"],
            content=payload["content"],
            category=payload["category"],
            sub_category=payload.get("sub_category"),
            doc_no=payload.get("doc_no"),
            issuing_authority=payload.get("issuing_authority"),
            article_no=payload.get("article_no"),
            effective_date=payload.get("effective_date"),
            expiry_date=payload.get("expiry_date"),
            timeliness=payload.get("timeliness") or "unknown",
            keywords=payload.get("keywords"),
            difficulty=payload.get("difficulty") or 1,
            source_type="manual",
            primary_chunk_id=payload.get("primary_chunk_id"),
            status=payload.get("status") or "draft",
            verify_status="pending",
            created_by=user.id,
            created_at=now(),
            updated_at=now(),
        )
        # 主来源冗余
        if kp.primary_chunk_id:
            chunk = db.get(DocumentChunk, kp.primary_chunk_id)
            kp.primary_document_id = chunk.document_id if chunk else None
        db.add(kp)
        db.flush()  # 先插入取 id，再回填业务编号（docs/03 §2.5）
        kp.code = self._next_code(db, kp.category, kp.id)
        db.commit()
        self._index_kp(kp)
        return self.to_dict(kp)

    def update(self, db: Session, kp_id: int, payload: dict) -> dict:
        kp = self.get(db, kp_id)
        if payload.get("primary_chunk_id") is not None:
            self._check_chunk(db, payload["primary_chunk_id"], kp.kb_id)
        for key, value in payload.items():
            if value is not None and hasattr(kp, key):
                setattr(kp, key, value)
        if payload.get("primary_chunk_id"):
            chunk = db.get(DocumentChunk, kp.primary_chunk_id)
            kp.primary_document_id = chunk.document_id if chunk else kp.primary_document_id
        kp.updated_at = now()
        db.commit()
        self._index_kp(kp)
        return self.to_dict(kp)

    def delete(self, db: Session, kp_id: int) -> dict:
        kp = self.get(db, kp_id)
        # 级联：来源关联 + 关联关系 + Milvus（docs/03 §6.4）
        db.query(KnowledgePointSource).filter(
            KnowledgePointSource.knowledge_point_id == kp_id
        ).delete()
        db.query(KnowledgePointRelation).filter(
            or_(
                KnowledgePointRelation.source_kp_id == kp_id,
                KnowledgePointRelation.target_kp_id == kp_id,
            )
        ).delete()
        db.delete(kp)
        db.commit()
        indexer.delete_kp(kp_id)
        return {"id": kp_id, "deleted": True}

    def verify(self, db: Session, kp_id: int, reviewer: User, payload: dict) -> dict:
        kp = self.get(db, kp_id)
        kp.verify_status = payload["verify_status"]
        kp.verified_by = reviewer.id
        kp.verified_at = now()
        kp.verify_comment = payload.get("comment")
        if payload.get("confidence") is not None:
            kp.confidence = payload["confidence"]
        kp.updated_at = now()
        # 同时写入 qa_review（target_type='knowledge_point'），用于统计校验通过率
        review = db.scalar(
            select(QAReview).where(
                QAReview.reviewer_id == reviewer.id,
                QAReview.target_type == "knowledge_point",
                QAReview.target_id == kp_id,
            )
        )
        is_correct = 1 if payload["verify_status"] == "passed" else 0
        if review is None:
            db.add(
                QAReview(
                    target_type="knowledge_point",
                    target_id=kp_id,
                    reviewer_id=reviewer.id,
                    is_correct=is_correct,
                    comment=payload.get("comment"),
                    created_at=now(),
                )
            )
        else:
            review.is_correct = is_correct
            review.comment = payload.get("comment")
        db.commit()
        return {
            "id": kp.id,
            "verify_status": kp.verify_status,
            "verified_by": kp.verified_by,
            "verified_at": kp.verified_at.strftime("%Y-%m-%d %H:%M:%S") if kp.verified_at else None,
            "verify_comment": kp.verify_comment,
        }

    # ---------------------------------------------------------------- 导入导出
    def import_file(
        self, db: Session, user: User, kb_id: int, file_name: str, data: bytes, dry_run: bool
    ) -> dict:
        """批量导入（Excel/CSV），dry_run=true 只校验不写库（docs/06 §5.6）。"""
        rows = self._parse_import_file(file_name, data)
        errors: List[dict] = []
        duplicates: List[dict] = []
        preview: List[dict] = []
        valid_rows: List[dict] = []

        for i, row in enumerate(rows, start=2):  # 第 1 行为表头
            err = self._validate_import_row(row)
            if err:
                errors.append({"row": i, "field": err[0], "message": err[1]})
                continue
            code = (row.get("code") or "").strip()
            if code:
                exists = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code))
                if exists is not None:
                    duplicates.append(
                        {"row": i, "code": code, "message": "编号已存在，将被更新"}
                    )
            valid_rows.append(row)
            preview.append({"row": i, "title": row.get("title"), "action": "create" if not code else "update"})

        result = {
            "dry_run": dry_run,
            "total_rows": len(rows),
            "valid_rows": len(valid_rows),
            "errors": errors[:100],
            "duplicates": duplicates[:100],
            "preview": preview[:50],
        }
        if dry_run:
            return result

        created = updated = skipped = 0
        for row in valid_rows:
            try:
                self._upsert_import_row(db, user, kb_id, row)
                if (row.get("code") or "").strip():
                    updated += 1
                else:
                    created += 1
            except Exception:
                skipped += 1
        db.commit()
        result.update({"created": created, "updated": updated, "skipped": skipped})
        return result

    def export(self, db: Session, kb_id: Optional[int]) -> List[dict]:
        query = select(KnowledgePoint)
        if kb_id:
            query = query.where(KnowledgePoint.kb_id == kb_id)
        rows = db.scalars(query.order_by(KnowledgePoint.id)).all()
        return [
            {
                "code": kp.code,
                "title": kp.title,
                "content": kp.content,
                "category": kp.category,
                "sub_category": kp.sub_category,
                "doc_no": kp.doc_no,
                "issuing_authority": kp.issuing_authority,
                "article_no": kp.article_no,
                "effective_date": kp.effective_date.strftime("%Y-%m-%d") if kp.effective_date else None,
                "expiry_date": kp.expiry_date.strftime("%Y-%m-%d") if kp.expiry_date else None,
                "timeliness": kp.timeliness,
                "keywords": kp.keywords,
                "difficulty": kp.difficulty,
                "status": kp.status,
            }
            for kp in rows
        ]

    # ---------------------------------------------------------------- 来源
    def sources(self, db: Session, kp_id: int) -> List[dict]:
        self.get(db, kp_id)
        rows = db.scalars(
            select(KnowledgePointSource)
            .where(KnowledgePointSource.knowledge_point_id == kp_id)
            .order_by(KnowledgePointSource.is_primary.desc())
        ).all()
        return [
            {
                "source_id": s.id,
                "chunk_id": s.chunk_id,
                "document_id": s.document_id,
                "page_no": s.page_no,
                "article_no": s.article_no,
                "quote_text": s.quote_text,
                "is_primary": s.is_primary,
            }
            for s in rows
        ]

    def bind_source(self, db: Session, kp_id: int, payload: dict) -> dict:
        kp = self.get(db, kp_id)
        chunk = db.get(DocumentChunk, payload["chunk_id"])
        if chunk is None:
            raise BizError(ErrorCode.NOT_FOUND, "切片不存在")
        exists = db.scalar(
            select(KnowledgePointSource).where(
                KnowledgePointSource.knowledge_point_id == kp_id,
                KnowledgePointSource.chunk_id == payload["chunk_id"],
            )
        )
        if exists is not None:
            raise BizError(ErrorCode.CONFLICT, "该来源切片已绑定")
        if payload.get("is_primary"):
            kp.primary_chunk_id = chunk.id
            kp.primary_document_id = chunk.document_id
        source = KnowledgePointSource(
            knowledge_point_id=kp_id,
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            page_no=chunk.page_start,
            article_no=chunk.article_no,
            quote_text=payload.get("quote_text"),
            is_primary=payload.get("is_primary") or 0,
            created_at=now(),
        )
        db.add(source)
        db.commit()
        return {"source_id": source.id, "chunk_id": chunk.id}

    def unbind_source(self, db: Session, kp_id: int, source_id: int) -> dict:
        source = db.scalar(
            select(KnowledgePointSource).where(
                KnowledgePointSource.id == source_id,
                KnowledgePointSource.knowledge_point_id == kp_id,
            )
        )
        if source is None:
            raise BizError(ErrorCode.NOT_FOUND, "来源关联不存在")
        db.delete(source)
        db.commit()
        return {"source_id": source_id, "deleted": True}

    # ---------------------------------------------------------------- 关联（FR-32）
    def related(self, db: Session, kp_id: int) -> dict:
        """三类关联：context 同制度上下文 / same_topic 同主题 / supersede 替代（docs/05 §11）。"""
        kp = self.get(db, kp_id)
        context = self._context_chunks(db, kp)
        same_topic = self._same_topic(db, kp)
        supersede = self._supersede(db, kp)
        return {
            "knowledge_point_id": kp_id,
            "context": context,
            "same_topic": same_topic,
            "supersede": supersede,
        }

    def _context_chunks(self, db: Session, kp: KnowledgePoint) -> List[dict]:
        if not kp.primary_chunk_id:
            return []
        primary = db.get(DocumentChunk, kp.primary_chunk_id)
        if primary is None:
            return []
        rows = db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == primary.document_id,
                DocumentChunk.chunk_index.between(
                    primary.chunk_index - 2, primary.chunk_index + 2
                ),
                DocumentChunk.id != primary.id,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(4)
        ).all()
        doc = db.get(Document, primary.document_id)
        return [
            {
                "chunk_id": c.id,
                "article_no": c.article_no,
                "page_no": c.page_start,
                "doc_title": doc.title if doc else None,
                "snippet": (c.raw_content or "")[:160],
            }
            for c in rows
        ]

    def _same_topic(self, db: Session, kp: KnowledgePoint) -> List[dict]:
        """优先读 knowledge_point_relation 表（离线任务每日重建），无数据时实时计算并回填。"""
        cached = db.scalars(
            select(KnowledgePointRelation).where(
                KnowledgePointRelation.source_kp_id == kp.id,
                KnowledgePointRelation.relation_type == "same_topic",
            )
        ).all()
        if cached:
            result = []
            for rel in cached[:5]:
                target = db.get(KnowledgePoint, rel.target_kp_id)
                if target is not None:
                    result.append(self._related_dict(target, rel.score))
            return result

        # 实时计算：用知识点向量检索 COSINE ≥ 0.75，排除自身与同文档
        try:
            vector = encode_query(f"{kp.title}\n{kp.content}")
            rows = indexer.search(
                vector=vector,
                expr=build_filter(categories=[kp.category], source_types=["knowledge_point"]),
                limit=12,
            )
        except Exception:
            return []
        result = []
        for row in rows:
            if int(row.get("source_id") or 0) == kp.id:
                continue
            distance = float(row.get("distance") or 0)
            if distance < 0.75:
                continue
            target = db.get(KnowledgePoint, int(row["source_id"]))
            if target is None or target.primary_document_id == kp.primary_document_id:
                continue
            result.append(self._related_dict(target, distance))
            # 回填缓存表
            db.add(
                KnowledgePointRelation(
                    source_kp_id=kp.id,
                    target_kp_id=target.id,
                    relation_type="same_topic",
                    score=round(distance, 4),
                    created_at=now(),
                )
            )
            if len(result) >= 5:
                break
        db.commit()
        return result

    def _supersede(self, db: Session, kp: KnowledgePoint) -> List[dict]:
        """沿 document.superseded_by 链上下各一层 + knowledge_point_relation.supersede。"""
        result: List[dict] = []
        if kp.primary_document_id:
            doc = db.get(Document, kp.primary_document_id)
            if doc is not None:
                if doc.superseded_by:
                    new_doc = db.get(Document, doc.superseded_by)
                    if new_doc is not None:
                        target = db.scalar(
                            select(KnowledgePoint).where(
                                KnowledgePoint.primary_document_id == new_doc.id,
                                KnowledgePoint.article_no == kp.article_no,
                            )
                        )
                        if target is not None:
                            result.append(self._supersede_dict(target, "supersede"))
                old_docs = db.scalars(
                    select(Document).where(Document.superseded_by == doc.id)
                ).all()
                for old_doc in old_docs[:1]:
                    target = db.scalar(
                        select(KnowledgePoint).where(
                            KnowledgePoint.primary_document_id == old_doc.id,
                            KnowledgePoint.article_no == kp.article_no,
                        )
                    )
                    if target is not None:
                        result.append(self._supersede_dict(target, "supersede"))
        rels = db.scalars(
            select(KnowledgePointRelation).where(
                KnowledgePointRelation.source_kp_id == kp.id,
                KnowledgePointRelation.relation_type == "supersede",
            )
        ).all()
        for rel in rels[:3]:
            target = db.get(KnowledgePoint, rel.target_kp_id)
            if target is not None:
                result.append(self._supersede_dict(target, "supersede"))
        return result[:3]

    # ---------------------------------------------------------------- 统计
    def stats(self, db: Session) -> dict:
        total = db.scalar(select(func.count()).select_from(KnowledgePoint)) or 0
        by_status = dict(
            db.execute(
                select(KnowledgePoint.status, func.count()).group_by(KnowledgePoint.status)
            ).all()
        )
        by_category = [
            {"category": r[0], "count": int(r[1]), "published": int(r[2])}
            for r in db.execute(
                select(
                    KnowledgePoint.category,
                    func.count(),
                    func.sum(KnowledgePoint.status == "published"),
                ).group_by(KnowledgePoint.category)
            ).all()
        ]
        by_verify = [
            {"verify_status": r[0], "count": int(r[1])}
            for r in db.execute(
                select(KnowledgePoint.verify_status, func.count()).group_by(
                    KnowledgePoint.verify_status
                )
            ).all()
        ]
        by_timeliness = [
            {"timeliness": r[0], "count": int(r[1])}
            for r in db.execute(
                select(KnowledgePoint.timeliness, func.count()).group_by(
                    KnowledgePoint.timeliness
                )
            ).all()
        ]
        by_sub = [
            {"sub_category": r[0], "count": int(r[1])}
            for r in db.execute(
                select(KnowledgePoint.sub_category, func.count())
                .where(KnowledgePoint.sub_category.is_not(None))
                .group_by(KnowledgePoint.sub_category)
            ).all()
        ]
        without_source = db.scalar(
            select(func.count())
            .select_from(KnowledgePoint)
            .where(KnowledgePoint.primary_chunk_id.is_(None))
        ) or 0
        return {
            "total": int(total),
            "draft": int(by_status.get("draft", 0)),
            "published": int(by_status.get("published", 0)),
            "archived": int(by_status.get("archived", 0)),
            "by_category": by_category,
            "by_verify_status": by_verify,
            "by_timeliness": by_timeliness,
            "by_sub_category": by_sub,
            "without_source": int(without_source),
            "coverage_rate": round(1 - without_source / total, 3) if total else None,
        }

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def to_dict(kp: KnowledgePoint) -> dict:
        return {
            "id": kp.id,
            "kb_id": kp.kb_id,
            "code": kp.code,
            "title": kp.title,
            "content": kp.content,
            "category": kp.category,
            "sub_category": kp.sub_category,
            "doc_no": kp.doc_no,
            "issuing_authority": kp.issuing_authority,
            "article_no": kp.article_no,
            "effective_date": kp.effective_date.strftime("%Y-%m-%d") if kp.effective_date else None,
            "expiry_date": kp.expiry_date.strftime("%Y-%m-%d") if kp.expiry_date else None,
            "timeliness": kp.timeliness,
            "keywords": kp.keywords,
            "difficulty": kp.difficulty,
            "source_type": kp.source_type,
            "primary_document_id": kp.primary_document_id,
            "primary_chunk_id": kp.primary_chunk_id,
            "confidence": float(kp.confidence) if kp.confidence is not None else None,
            "verify_status": kp.verify_status,
            "verified_by": kp.verified_by,
            "verified_at": kp.verified_at.strftime("%Y-%m-%d %H:%M:%S") if kp.verified_at else None,
            "status": kp.status,
            "created_at": kp.created_at.strftime("%Y-%m-%d %H:%M:%S") if kp.created_at else None,
            "updated_at": kp.updated_at.strftime("%Y-%m-%d %H:%M:%S") if kp.updated_at else None,
        }

    @staticmethod
    def _next_code(db: Session, category: str, kp_id: int) -> str:
        prefix = KP_CODE_PREFIX.get(category, "KP-GEN")
        return f"{prefix}-{kp_id:04d}"

    @staticmethod
    def _check_chunk(db: Session, chunk_id: Optional[int], kb_id: int) -> None:
        if not chunk_id:
            return
        chunk = db.get(DocumentChunk, chunk_id)
        if chunk is None:
            raise BizError(ErrorCode.PARAM_INVALID, "primary_chunk_id 不存在")
        if chunk.kb_id != kb_id:
            raise BizError(ErrorCode.PARAM_INVALID, "primary_chunk_id 必须属于同一知识库")

    def _index_kp(self, kp: KnowledgePoint) -> None:
        """知识点单独向量化入 Milvus（source_type=knowledge_point，ADR-09）。"""
        try:
            vector = encode_query(f"{kp.title}\n{kp.content}")
            indexer.upsert(
                [
                    {
                        "pk": f"kp_{kp.id}",
                        "embedding": vector,
                        "source_type": "knowledge_point",
                        "source_id": kp.id,
                        "kb_id": kp.kb_id,
                        "document_id": kp.primary_document_id or 0,
                        "category": kp.category,
                        "timeliness": kp.timeliness,
                        "article_no": kp.article_no or "",
                        "page_no": 0,
                        "chunk_index": -1,
                        "publish_year": kp.effective_date.year if kp.effective_date else 0,
                        "content": f"{kp.title}\n{kp.content}",
                    }
                ]
            )
        except Exception as exc:  # 向量失败不阻断知识点维护，可重新保存触发重建
            from loguru import logger

            logger.warning("知识点 {} 向量化失败: {}", kp.id, exc)

    # ------------------------------------------------------------ 导入细节
    @staticmethod
    def _parse_import_file(file_name: str, data: bytes) -> List[dict]:
        name = file_name.lower()
        if name.endswith(".csv"):
            text = data.decode("utf-8-sig", errors="ignore")
            reader = csv.DictReader(io.StringIO(text))
            return [dict(r) for r in reader]
        if name.endswith(".xlsx"):
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header = [str(h).strip() if h else "" for h in next(rows_iter, ())]
            out = []
            for row in rows_iter:
                out.append(
                    {header[i]: (str(row[i]).strip() if row[i] is not None else "")
                     for i in range(min(len(header), len(row)))}
                )
            return out
        raise BizError(ErrorCode.FILE_TYPE_NOT_ALLOWED, "导入文件仅支持 .xlsx 或 .csv")

    @staticmethod
    def _validate_import_row(row: dict) -> Optional[Tuple[str, str]]:
        title = (row.get("title") or "").strip()
        content = (row.get("content") or "").strip()
        category = (row.get("category") or "").strip()
        if not title or not (5 <= len(title) <= 300):
            return "title", "标题长度须为 5~300 字"
        if len(content) < 10:
            return "content", "内容长度不足 10 字"
        if len(content) > 2000:
            return "content", "内容长度超过 2000 字"
        if category not in CATEGORY_SUB:
            return "category", "分类必须是 banking/securities/insurance"
        sub = (row.get("sub_category") or "").strip()
        if sub and sub not in CATEGORY_SUB[category]:
            return "sub_category", f"子分类不属于 {category} 的合法取值"
        return None

    def _upsert_import_row(self, db: Session, user: User, kb_id: int, row: dict) -> None:
        from app.utils.time import parse_date

        code = (row.get("code") or "").strip()
        kp = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code)) if code else None
        fields = {
            "kb_id": kb_id,
            "title": row.get("title"),
            "content": row.get("content"),
            "category": row.get("category"),
            "sub_category": row.get("sub_category") or None,
            "doc_no": row.get("doc_no") or None,
            "issuing_authority": row.get("issuing_authority") or None,
            "article_no": row.get("article_no") or None,
            "effective_date": parse_date(row.get("effective_date")),
            "expiry_date": parse_date(row.get("expiry_date")),
            "timeliness": row.get("timeliness") or "unknown",
            "keywords": row.get("keywords") or None,
            "difficulty": int(row.get("difficulty") or 1),
            "status": row.get("status") or "published",
        }
        if kp is None:
            kp = KnowledgePoint(
                source_type="import",
                verify_status="pending",
                created_by=user.id,
                created_at=now(),
                updated_at=now(),
                **fields,
            )
            db.add(kp)
            db.flush()
            kp.code = code or self._next_code(db, kp.category, kp.id)
        else:
            for key, value in fields.items():
                setattr(kp, key, value)
            kp.updated_at = now()


knowledge_point_service = KnowledgePointService()
