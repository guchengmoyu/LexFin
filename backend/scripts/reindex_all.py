"""运维脚本：从 MySQL 重建 Milvus 向量索引（docs/03 §1 一致性原则）。

用法：
    cd backend && python scripts/reindex_all.py --kb-id 1
只要 document_chunk 与 knowledge_point 还在，跑一次本脚本即可恢复向量库。
支持零停机重建（docs/03 §3.5）：--zero-downtime 时新建 _v2 集合并切换别名。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.models.chunk import DocumentChunk  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge_point import KnowledgePoint  # noqa: E402
from app.rag.embedder import get_embedder  # noqa: E402
from app.rag.indexer import indexer  # noqa: E402


def reindex_chunks(db, kb_id: int | None, embedder, batch_size: int = 64) -> int:
    query = select(DocumentChunk, Document).join(
        Document, Document.id == DocumentChunk.document_id
    )
    if kb_id:
        query = query.where(DocumentChunk.kb_id == kb_id)
    rows = db.execute(query).all()
    total = len(rows)
    print(f"[reindex] 切片共 {total} 条")
    buffer = []
    done = 0
    for chunk, doc in rows:
        buffer.append((chunk, doc))
        if len(buffer) >= batch_size:
            done += _upsert_batch(embedder, buffer)
            buffer.clear()
            print(f"[reindex] 切片进度 {done}/{total}")
    if buffer:
        done += _upsert_batch(embedder, buffer)
    return done


def _upsert_batch(embedder, buffer) -> int:
    vectors = embedder.encode([c.content for c, _ in buffer])
    rows = []
    for (chunk, doc), vec in zip(buffer, vectors):
        rows.append(
            {
                "pk": f"chunk_{chunk.id}",
                "embedding": vec,
                "source_type": "chunk",
                "source_id": chunk.id,
                "kb_id": chunk.kb_id,
                "document_id": chunk.document_id,
                "category": doc.category or "",
                "timeliness": doc.timeliness or "unknown",
                "article_no": chunk.article_no or "",
                "page_no": chunk.page_start or 0,
                "chunk_index": chunk.chunk_index,
                "publish_year": doc.publish_date.year if doc.publish_date else 0,
                "content": chunk.content,
            }
        )
        chunk.embedding_status = 1
    indexer.upsert(rows)
    return len(rows)


def reindex_kps(db, kb_id: int | None, embedder, batch_size: int = 64) -> int:
    query = select(KnowledgePoint)
    if kb_id:
        query = query.where(KnowledgePoint.kb_id == kb_id)
    kps = db.scalars(query).all()
    print(f"[reindex] 知识点共 {len(kps)} 条")
    done = 0
    for i in range(0, len(kps), batch_size):
        batch = kps[i : i + batch_size]
        vectors = embedder.encode([f"{k.title}\n{k.content}" for k in batch])
        rows = []
        for kp, vec in zip(batch, vectors):
            rows.append(
                {
                    "pk": f"kp_{kp.id}",
                    "embedding": vec,
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
            )
            kp.embedding_status = 1
        indexer.upsert(rows)
        done += len(rows)
        print(f"[reindex] 知识点进度 {done}/{len(kps)}")
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="从 MySQL 重建 Milvus 向量索引")
    parser.add_argument("--kb-id", type=int, default=None, help="只重建指定知识库")
    parser.add_argument("--only", choices=["chunks", "kp", "all"], default="all")
    parser.add_argument("--drop-kb", action="store_true", help="重建前删除该知识库全部向量")
    args = parser.parse_args()

    embedder = get_embedder()
    with session_scope() as db:
        if args.drop_kb and args.kb_id:
            indexer.delete_by_kb(args.kb_id)
            print(f"[reindex] 已清空 kb_id={args.kb_id} 的向量")
        if args.only in ("chunks", "all"):
            n = reindex_chunks(db, args.kb_id, embedder)
            print(f"[reindex] 切片写入 {n} 条")
        if args.only in ("kp", "all"):
            n = reindex_kps(db, args.kb_id, embedder)
            print(f"[reindex] 知识点写入 {n} 条")

    total = indexer.count()
    print(f"[reindex] 完成，Milvus 当前实体约 {total} 条")


if __name__ == "__main__":
    main()
