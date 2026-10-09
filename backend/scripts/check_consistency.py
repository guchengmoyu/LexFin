"""一致性巡检（docs/02 §7.5）：比对 MySQL 切片数与 Milvus 实体数，输出差异清单。

用法：cd backend && python scripts/check_consistency.py [--fix]
--fix 时对差异文档自动重放向量写入（先删后建，幂等）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import session_scope  # noqa: E402
from app.models.chunk import DocumentChunk  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.rag.indexer import indexer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="MySQL ↔ Milvus 一致性巡检")
    parser.add_argument("--fix", action="store_true", help="自动修复差异（重新向量化）")
    args = parser.parse_args()

    with session_scope() as db:
        docs = db.scalars(select(Document).where(Document.status == "ready")).all()
        print(f"{'doc_id':>8} {'title':<40} {'mysql':>8} {'milvus':>8} {'diff':>6}")
        diff_docs = []
        for doc in docs:
            mysql_count = db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.document_id == doc.id)
            ) or 0
            milvus_count = indexer.count(f"document_id == {doc.id}")
            diff = mysql_count - milvus_count
            if diff != 0:
                diff_docs.append(doc.id)
            print(f"{doc.id:>8} {(doc.title or '')[:38]:<40} {mysql_count:>8} {milvus_count:>8} {diff:>6}")

        total_mysql = db.scalar(select(func.count()).select_from(DocumentChunk)) or 0
        total_milvus = indexer.count('source_type == "chunk"')
        print(f"\n合计：MySQL {total_mysql} 切片 / Milvus {total_milvus} 切片实体")
        if not diff_docs:
            print("✅ 一致性检查通过")
            return

        print(f"⚠ 发现 {len(diff_docs)} 个文档存在差异：{diff_docs}")
        if args.fix:
            from scripts.reindex_all import _upsert_batch

            from app.rag.embedder import get_embedder

            embedder = get_embedder()
            for doc_id in diff_docs:
                indexer.delete_by_document(doc_id)
                rows = db.execute(
                    select(DocumentChunk, Document)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(DocumentChunk.document_id == doc_id)
                ).all()
                buffer = [(c, d) for c, d in rows]
                for i in range(0, len(buffer), 64):
                    _upsert_batch(embedder, buffer[i : i + 64])
                print(f"[fix] 文档 {doc_id} 重建完成，{len(buffer)} 块")
        else:
            print("可执行 `python scripts/check_consistency.py --fix` 自动修复")


if __name__ == "__main__":
    main()
