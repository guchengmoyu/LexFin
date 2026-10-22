"""文档服务（docs/06 §5.4）：上传、列表、详情、删除级联、切片、下载、元数据预览。"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import DocStatus, ErrorCode, TaskType
from app.core.exceptions import BizError
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_point import KnowledgePoint
from app.models.knowledge_point import KnowledgePointSource
from app.models.task import IngestTask
from app.models.user import User
from app.rag.indexer import indexer
from app.utils.file import safe_store
from app.utils.time import gen_no, now


class DocumentService:
    # ---------------------------------------------------------------- 上传
    def upload(
        self,
        db: Session,
        user: User,
        file_name: str,
        data: bytes,
        kb_id: int,
        meta: dict,
    ) -> dict:
        """受理单个文件：校验 → 落盘 → 落 document(pending) + ingest_task(queued)。"""
        from app.services.kb import kb_service

        kb_service.get(db, kb_id)  # 校验知识库存在

        try:
            file_path, stored_name, file_md5 = safe_store(file_name, data)
        except BizError as exc:
            return {
                "file_name": file_name,
                "success": False,
                "code": exc.code,
                "message": exc.message,
                "document_id": None,
            }

        # 同知识库重复上传同一文件 → 40901（uk_kb_md5）
        dup = db.scalar(
            select(Document).where(Document.kb_id == kb_id, Document.file_md5 == file_md5)
        )
        if dup is not None and dup.status != DocStatus.archived.value:
            return {
                "file_name": file_name,
                "success": False,
                "code": ErrorCode.DOCUMENT_DUPLICATE,
                "message": "该文件已存在于本知识库",
                "document_id": dup.id,
            }

        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise BizError(ErrorCode.NOT_FOUND, "知识库不存在")
        document = Document(
            kb_id=kb_id,
            title=(meta.get("title") or file_name.rsplit(".", 1)[0])[:300],
            doc_no=meta.get("doc_no"),
            doc_type=meta.get("doc_type") or "regulation",
            category=kb.category,
            issuing_authority=meta.get("issuing_authority"),
            publish_date=meta.get("publish_date"),
            effective_date=meta.get("effective_date"),
            expiry_date=meta.get("expiry_date"),
            timeliness=meta.get("timeliness") or "unknown",
            file_name=file_name,
            file_path=file_path,
            file_ext="." + stored_name.rsplit(".", 1)[-1],
            file_size=len(data),
            file_md5=file_md5,
            status=DocStatus.pending.value,
            keywords=meta.get("keywords"),
            uploaded_by=user.id,
            created_at=now(),
            updated_at=now(),
        )
        db.add(document)
        db.flush()

        task = IngestTask(
            task_no=gen_no("t"),
            document_id=document.id,
            kb_id=kb_id,
            task_type=TaskType.ingest.value,
            status="queued",
            progress=0,
            stage_message="排队中",
            created_by=user.id,
            created_at=now(),
        )
        db.add(task)
        db.commit()

        return {
            "file_name": file_name,
            "success": True,
            "document_id": document.id,
            "task_no": task.task_no,
            "status": "pending",
        }

    # ---------------------------------------------------------------- 查询
    def list(self, db: Session, filters: dict, page: int, size: int) -> dict:
        query = select(Document).where(Document.status != DocStatus.archived.value)
        if filters.get("kb_id"):
            query = query.where(Document.kb_id == filters["kb_id"])
        if filters.get("category"):
            query = query.where(Document.category == filters["category"])
        if filters.get("status"):
            query = query.where(Document.status == filters["status"])
        if filters.get("doc_type"):
            query = query.where(Document.doc_type == filters["doc_type"])
        if filters.get("timeliness"):
            query = query.where(Document.timeliness == filters["timeliness"])
        if filters.get("keyword"):
            like = f"%{filters['keyword']}%"
            query = query.where(Document.title.like(like) | Document.doc_no.like(like))

        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        sort_col = Document.created_at
        if filters.get("sort") == "publish_date":
            sort_col = Document.publish_date
        rows = db.scalars(
            query.order_by(sort_col.desc()).offset((page - 1) * size).limit(size)
        ).all()
        items = [self._list_dict(doc) for doc in rows]
        from app.core.response import paged

        return paged(total, page, size, items)

    def get(self, db: Session, doc_id: int) -> Document:
        doc = db.get(Document, doc_id)
        if doc is None or doc.status == DocStatus.archived.value:
            raise BizError(ErrorCode.DOCUMENT_NOT_FOUND, "文档不存在")
        return doc

    def detail(self, db: Session, doc_id: int) -> dict:
        doc = self.get(db, doc_id)
        data = self._list_dict(doc)
        data.update(
            {
                "file_ext": doc.file_ext,
                "file_md5": doc.file_md5,
                "keywords": doc.keywords,
                "uploaded_by": doc.uploaded_by,
                "superseded_by": doc.superseded_by,
                "warnings": (doc.error_message or "").split("；") if doc.error_message else [],
            }
        )
        return data

    def update(self, db: Session, doc_id: int, payload: dict) -> dict:
        doc = self.get(db, doc_id)
        for key, value in payload.items():
            if value is not None and hasattr(doc, key):
                setattr(doc, key, value)
        doc.updated_at = now()
        db.commit()
        return self.detail(db, doc_id)

    def chunks(self, db: Session, doc_id: int, page: int, size: int) -> dict:
        self.get(db, doc_id)
        total = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        ) or 0
        rows = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
            .offset((page - 1) * size)
            .limit(size)
        ).all()
        # 列表接口不返回 content 大字段（docs/03 §6.6）
        items = [
            {
                "id": c.id,
                "chunk_index": c.chunk_index,
                "chapter_no": c.chapter_no,
                "article_no": c.article_no,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "char_count": c.char_count,
                "source_type": c.source_type,
                "embedding_status": c.embedding_status,
                "raw_content": (c.raw_content or "")[:300],
            }
            for c in rows
        ]
        from app.core.response import paged

        return paged(total, page, size, items)

    def download_path(self, db: Session, doc_id: int) -> Tuple[str, str]:
        """返回 (绝对路径, 文件名)；路径一律来自数据库（防路径穿越）。"""
        doc = self.get(db, doc_id)
        return doc.file_path, doc.file_name

    # ---------------------------------------------------------------- 删除
    def delete(self, db: Session, doc_id: int, hard: bool = False) -> dict:
        """级联删除（docs/06 §5.4 / docs/03 §6.4，由 Service 编排）。"""
        doc = self.get(db, doc_id)
        chunk_count = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        ) or 0

        # 1) 删除 document_chunk
        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).delete()
        # 2) 删除 Milvus 向量
        indexer.delete_by_document(doc_id)
        # 3) 清理知识点来源关联；4) 受影响知识点置空 primary 并标记存疑
        sources = db.scalars(
            select(KnowledgePointSource).where(KnowledgePointSource.document_id == doc_id)
        ).all()
        affected_kp_ids = {s.knowledge_point_id for s in sources}
        for s in sources:
            db.delete(s)
        for kp_id in affected_kp_ids:
            kp = db.get(KnowledgePoint, kp_id)
            if kp is not None:
                kp.primary_chunk_id = None
                kp.verify_status = "doubted"
                kp.updated_at = now()
        # 5) 软删除（?hard=true 彻底删除，物理文件保留）
        if hard:
            db.delete(doc)
        else:
            doc.status = DocStatus.archived.value
            doc.updated_at = now()
        db.commit()
        return {
            "document_id": doc_id,
            "deleted_chunks": int(chunk_count),
            "deleted_vectors": int(chunk_count),
            "affected_knowledge_points": len(affected_kp_ids),
        }

    def extract_meta_preview(self, db: Session, file_name: str, data: bytes) -> dict:
        """解析预览（不落库，docs/06 §5.4 extract-meta）。"""
        import tempfile
        from pathlib import Path

        from app.rag.parser.registry import parse_document

        with tempfile.TemporaryDirectory() as tmp:
            suffix = Path(file_name).suffix.lower()
            tmp_path = Path(tmp) / f"preview{suffix}"
            tmp_path.write_bytes(data)
            parsed = parse_document(str(tmp_path))

        preview_text = "\n".join(
            b.text for p in parsed.pages[:2] for b in p.blocks
        )[:1000]
        return {
            "file_name": file_name,
            "page_count": len(parsed.pages),
            "parse_method": parsed.parse_method,
            "char_count": sum(p.char_count for p in parsed.pages),
            "detected": {
                "title": parsed.meta.get("title"),
                "doc_no": parsed.meta.get("doc_no"),
                "issuing_authority": parsed.meta.get("issuing_authority"),
                "publish_date": parsed.meta.get("publish_date"),
                "effective_date": parsed.meta.get("effective_date"),
            },
            "preview_text": preview_text,
        }

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def _list_dict(doc: Document) -> dict:
        return {
            "id": doc.id,
            "kb_id": doc.kb_id,
            "title": doc.title,
            "doc_no": doc.doc_no,
            "doc_type": doc.doc_type,
            "category": doc.category,
            "issuing_authority": doc.issuing_authority,
            "publish_date": doc.publish_date.strftime("%Y-%m-%d") if doc.publish_date else None,
            "effective_date": doc.effective_date.strftime("%Y-%m-%d") if doc.effective_date else None,
            "expiry_date": doc.expiry_date.strftime("%Y-%m-%d") if doc.expiry_date else None,
            "timeliness": doc.timeliness,
            "is_latest": doc.is_latest,
            "version": doc.version,
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "page_count": doc.page_count,
            "parse_method": doc.parse_method,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "error_message": doc.error_message,
            "created_at": doc.created_at.strftime("%Y-%m-%d %H:%M:%S") if doc.created_at else None,
        }


document_service = DocumentService()
