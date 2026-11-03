"""从 MySQL 构建 Milvus 2.5 原生 BM25 索引（docs/05 §3.2.1）。

数据来源与向量集合一致：
- document_chunk（950 条切片，只取所属文档已就绪的切片）；
- knowledge_point（published + passed，1225 条）。

用法：
    python scripts/build_bm25_index.py              # 增量 upsert，缺集合时自动创建
    python scripts/build_bm25_index.py --drop       # 先删集合重建（全量）
    python scripts/build_bm25_index.py --dry-run    # 只统计，不写 Milvus
    python scripts/build_bm25_index.py --analyzer standard
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db import milvus_bm25  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.models.chunk import DocumentChunk  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge_point import KnowledgePoint  # noqa: E402


def _doc_meta(db) -> Dict[int, Document]:
    return {doc.id: doc for doc in db.scalars(select(Document)).all()}


def _chunk_rows(db, docs: Dict[int, Document]) -> Iterable[dict]:
    rows = db.scalars(select(DocumentChunk).order_by(DocumentChunk.id)).all()
    for chunk in rows:
        doc = docs.get(chunk.document_id)
        if doc is None:
            continue
        yield {
            "pk": f"chunk_{chunk.id}",
            "source_type": "chunk",
            "source_id": chunk.id,
            "kb_id": chunk.kb_id,
            "document_id": chunk.document_id,
            "category": doc.category or "",
            "timeliness": doc.timeliness or "unknown",
            "article_no": chunk.article_no or "",
            "page_no": chunk.page_start or 0,
            "chunk_index": chunk.chunk_index or -1,
            "publish_year": doc.publish_date.year if doc.publish_date else 0,
            "doc_title": doc.title,
            "doc_no": doc.doc_no,
            "issuing_authority": doc.issuing_authority,
            "content": chunk.content,
            "text": chunk.content,
        }


def _kp_rows(db, docs: Dict[int, Document], chunks: Dict[int, DocumentChunk]) -> Iterable[dict]:
    stmt = select(KnowledgePoint).where(
        KnowledgePoint.status == "published",
        KnowledgePoint.verify_status == "passed",
    )
    for kp in db.scalars(stmt.order_by(KnowledgePoint.id)).all():
        doc = docs.get(kp.primary_document_id or 0)
        chunk = chunks.get(kp.primary_chunk_id or 0)
        text = f"{kp.title}\n{kp.content}" if kp.title else (kp.content or "")
        yield {
            "pk": f"kp_{kp.id}",
            "source_type": "knowledge_point",
            "source_id": kp.id,
            "kb_id": kp.kb_id,
            "document_id": kp.primary_document_id or 0,
            "category": kp.category or "",
            "timeliness": kp.timeliness or (doc.timeliness if doc else "unknown"),
            "article_no": kp.article_no or "",
            "page_no": (chunk.page_start if chunk else 0) or 0,
            "chunk_index": -1,
            "publish_year": doc.publish_date.year if doc and doc.publish_date else 0,
            "doc_title": doc.title if doc else None,
            "doc_no": doc.doc_no if doc else None,
            "issuing_authority": doc.issuing_authority if doc else None,
            "content": text,
            "text": text,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Milvus BM25 索引")
    parser.add_argument("--drop", action="store_true", help="先删除集合再重建")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写 Milvus")
    parser.add_argument("--analyzer", default=None, help="覆盖 settings.bm25_analyzer")
    parser.add_argument("--batch", type=int, default=100, help="每批写入条数")
    args = parser.parse_args()

    if args.analyzer:
        settings.bm25_analyzer = args.analyzer

    factory = get_session_factory()
    with factory() as db:
        docs = _doc_meta(db)
        chunks = {c.id: c for c in db.scalars(select(DocumentChunk)).all()}
        rows: List[dict] = list(_chunk_rows(db, docs)) + list(_kp_rows(db, docs, chunks))

    chunks = sum(1 for r in rows if r["source_type"] == "chunk")
    kps = len(rows) - chunks
    print(f"待写入：切片 {chunks} 条，知识点 {kps} 条，合计 {len(rows)} 条")
    print(f"集合：{milvus_bm25.collection_name()}（analyzer={settings.bm25_analyzer}）")
    if args.dry_run:
        print("dry-run：未写入 Milvus")
        return 0

    milvus_bm25.init_collection(drop=args.drop)
    if args.drop:
        print("已重建集合")
    written = milvus_bm25.upsert_rows(rows, batch_size=args.batch)
    print(f"写入完成：{written} 条，集合内当前 {milvus_bm25.count()} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
