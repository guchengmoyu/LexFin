"""入库服务（IngestService）：解析 → 清洗 → 切分 → 入库 → 向量化 → 索引（docs/02 §6.2）。

执行方式：FastAPI BackgroundTasks（ADR-06，无消息队列）；
前端按 1.5s 轮询 GET /tasks/{task_no} 获取进度。
幂等：reparse 先删除该文档已有切片（MySQL + Milvus）再重走全流程（docs/04 §8）。
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.core.constants import ErrorCode, TaskStatus
from app.core.exceptions import BizError
from app.db.session import session_scope
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.task import IngestTask
from app.rag.chunker import chunker
from app.rag.cleaner import cleaner
from app.rag.embedder import get_embedder
from app.rag.indexer import indexer
from app.rag.parser.registry import parse_document
from app.utils.time import gen_no, now

# 阶段 → 进度（docs/06 §5.5 状态映射）
STAGE_PROGRESS = {
    TaskStatus.queued.value: 0,
    TaskStatus.parsing.value: 10,
    TaskStatus.cleaning.value: 35,
    TaskStatus.chunking.value: 45,
    TaskStatus.embedding.value: 50,
    TaskStatus.indexing.value: 90,
    TaskStatus.success.value: 100,
}


class IngestService:
    # ---------------------------------------------------------------- 触发
    def start(self, db, task_no: str, task_type: str = "ingest") -> str:
        """校验任务存在且无并发任务（docs/02 §7.6），返回 task_no 供 BackgroundTasks 调度。"""
        task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
        if task is None:
            raise BizError(ErrorCode.NOT_FOUND, "任务不存在")
        running = db.scalar(
            select(IngestTask).where(
                IngestTask.document_id == task.document_id,
                IngestTask.status.notin_(["success", "failed"]),
                IngestTask.id != task.id,
            )
        )
        if running is not None:
            raise BizError(ErrorCode.TASK_RUNNING, "该文档已有进行中的入库任务")
        return task_no

    def reparse(self, db, doc_id: int, user_id: int) -> str:
        """重新解析：先删除已有切片（MySQL + Milvus）再重走全流程。"""
        doc = db.get(Document, doc_id)
        if doc is None:
            raise BizError(ErrorCode.DOCUMENT_NOT_FOUND, "文档不存在")
        self._purge_chunks(db, doc_id)
        task = IngestTask(
            task_no=gen_no("t"),
            document_id=doc_id,
            kb_id=doc.kb_id,
            task_type="reparse",
            status=TaskStatus.queued.value,
            progress=0,
            stage_message="排队中",
            created_by=user_id,
            created_at=now(),
        )
        doc.status = "pending"
        doc.error_message = None
        db.add(task)
        db.commit()
        return task.task_no

    # ---------------------------------------------------------------- 主流程
    def run(self, task_no: str) -> None:
        """后台执行入库全流程；任何异常 → task failed + document error。"""
        start_ts = time.perf_counter()
        with session_scope() as db:
            task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
            if task is None:
                return
            doc = db.get(Document, task.document_id)
            if doc is None:
                task.status = TaskStatus.failed.value
                task.error_message = "文档不存在"
                return
            task.status = TaskStatus.parsing.value
            task.progress = STAGE_PROGRESS[TaskStatus.parsing.value]
            task.stage_message = "正在解析文档"
            task.started_at = now()
            document_id = doc.id
            file_path = doc.file_path

        try:
            self._run_pipeline(task_no, document_id, file_path, start_ts)
        except BizError as exc:
            self._mark_failed(task_no, document_id, exc.message, start_ts)
        except Exception as exc:  # noqa: BLE001
            logger.exception("入库任务 {} 失败", task_no)
            self._mark_failed(task_no, document_id, f"文档解析失败：{exc}", start_ts)

    def _run_pipeline(self, task_no: str, document_id: int, file_path: str, start_ts: float) -> None:
        # ① 解析
        parsed = parse_document(file_path)
        with session_scope() as db:
            self._update_stage(db, task_no, TaskStatus.cleaning, "正在清洗文本")
            doc = db.get(Document, document_id)
            doc.page_count = len(parsed.pages)
            doc.parse_method = parsed.parse_method

        # ② 清洗 + ③ 切分
        with session_scope() as db:
            self._update_stage(db, task_no, TaskStatus.chunking, "正在切分条文")
            doc = db.get(Document, document_id)
            doc_meta = {
                "category": doc.category or "",
                "timeliness": doc.timeliness or "unknown",
                "publish_year": doc.publish_date.year if doc.publish_date else 0,
            }
            # Parser → Cleaner → Chunker（docs/04 §2），清洗保留块类型与页号
            cleaned_doc = cleaner.clean_parsed(parsed)
            raw_chunks = chunker.split(cleaned_doc, doc_title=doc.title, doc_no=doc.doc_no or "")
            if not raw_chunks:
                raise BizError(ErrorCode.PARSE_FAILED, "未能从文件中提取到有效文本")
            warnings = parsed.warnings + chunker.self_check(raw_chunks, len(parsed.pages))

            # ④ 先写 MySQL 拿到自增 id（docs/03 §3.4）
            chunk_rows: list[DocumentChunk] = []
            for idx, rc in enumerate(raw_chunks):
                chunk_rows.append(
                    DocumentChunk(
                        document_id=document_id,
                        kb_id=doc.kb_id,
                        chunk_index=idx,
                        chapter_no=rc.chapter_no,
                        article_no=rc.article_no,
                        page_start=rc.page_start,
                        page_end=rc.page_end,
                        content=rc.content,
                        raw_content=rc.raw_content,
                        char_count=rc.char_count,
                        source_type=rc.source_type,
                        embedding_status=0,
                        created_at=now(),
                    )
                )
            db.add_all(chunk_rows)
            db.flush()
            chunk_payload = [
                {
                    "id": c.id,
                    "content": c.content,
                    "kb_id": c.kb_id,
                    "article_no": c.article_no,
                    "page_start": c.page_start,
                    "chunk_index": c.chunk_index,
                }
                for c in chunk_rows
            ]
            task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
            task.total_chunks = len(chunk_rows)

        # ⑤ 向量化（batch=32）+ ⑥ 写 Milvus
        embedder = get_embedder()
        total = len(chunk_payload)
        done = 0
        rows = []
        batch_size = settings.embedding_batch_size
        with session_scope() as db:
            self._update_stage(
                db, task_no, TaskStatus.embedding,
                f"正在向量化切片 0/{total}", progress=STAGE_PROGRESS[TaskStatus.embedding.value],
            )
        for i in range(0, total, batch_size):
            batch = chunk_payload[i : i + batch_size]
            vectors = embedder.encode([c["content"] for c in batch])
            for c, vec in zip(batch, vectors):
                rows.append(
                    {
                        "pk": f"chunk_{c['id']}",
                        "embedding": vec,
                        "source_type": "chunk",
                        "source_id": c["id"],
                        "kb_id": c["kb_id"],
                        "document_id": document_id,
                        "category": doc_meta["category"],
                        "timeliness": doc_meta["timeliness"],
                        "article_no": c["article_no"] or "",
                        "page_no": c["page_start"] or 0,
                        "chunk_index": c["chunk_index"],
                        "publish_year": doc_meta["publish_year"],
                        "content": c["content"],
                    }
                )
            done += len(batch)
            progress = 50 + int(35 * done / max(1, total))
            with session_scope() as db:
                self._update_stage(
                    db, task_no, TaskStatus.embedding,
                    f"正在向量化切片 {done}/{total}", progress=progress,
                )
                for c in batch:
                    row = db.scalar(
                        select(DocumentChunk).where(DocumentChunk.id == c["id"])
                    )
                    if row is not None:
                        row.embedding_status = 1

        with session_scope() as db:
            self._update_stage(db, task_no, TaskStatus.indexing, "正在写入向量库")
        indexer.upsert(rows)

        # ⑦ 收尾：切片自检告警 + 状态流转
        with session_scope() as db:
            doc = db.get(Document, document_id)
            doc.chunk_count = total
            doc.status = "ready"
            if warnings:
                doc.error_message = "；".join(warnings)[:500]  # 黄色告警，不阻断
            doc.updated_at = now()
            task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
            task.status = TaskStatus.success.value
            task.progress = 100
            task.stage_message = "已完成"
            task.done_chunks = total
            task.finished_at = now()
            task.duration_ms = int((time.perf_counter() - start_ts) * 1000)

    # ---------------------------------------------------------------- 工具
    def _update_stage(self, db, task_no: str, status: TaskStatus, message: str,
                      progress: Optional[int] = None) -> None:
        task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
        if task is None:
            return
        task.status = status.value
        task.stage_message = message[:200]
        task.progress = progress if progress is not None else STAGE_PROGRESS[status.value]

    def _mark_failed(self, task_no: str, document_id: int, message: str, start_ts: float) -> None:
        with session_scope() as db:
            task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
            if task is not None:
                task.status = TaskStatus.failed.value
                task.error_message = message[:1000]
                task.stage_message = "失败"
                task.finished_at = now()
                task.duration_ms = int((time.perf_counter() - start_ts) * 1000)
            doc = db.get(Document, document_id)
            if doc is not None:
                doc.status = "error"
                doc.error_message = message[:500]
                doc.updated_at = now()

    def _purge_chunks(self, db, document_id: int) -> None:
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
        indexer.delete_by_document(document_id)


ingest_service = IngestService()
