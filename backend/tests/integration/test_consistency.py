"""一致性测试（docs/09 §4.1）：MySQL document_chunk 数 == Milvus 按 document_id
过滤的实体数；同时覆盖知识点向量（source_type=knowledge_point）。"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


async def test_mysql_milvus_chunk_count_consistent(db_session):
    from app.models.chunk import DocumentChunk
    from app.models.document import Document
    from app.rag.indexer import indexer

    try:
        indexer.count()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"需要 Milvus 就绪：{exc}")

    docs = db_session.scalars(
        select(Document).where(Document.status == "ready")
    ).all()
    mismatched = []
    for doc in docs:
        mysql_count = db_session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
        )
        milvus_count = indexer.count(f"document_id == {doc.id} and source_type == \"chunk\"")
        if mysql_count != milvus_count:
            mismatched.append((doc.id, mysql_count, milvus_count))
    assert not mismatched, f"MySQL↔Milvus 切片数不一致：{mismatched}"


async def test_knowledge_point_vectors_exist(db_session):
    from app.models.knowledge_point import KnowledgePoint
    from app.rag.indexer import indexer

    try:
        indexer.count()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"需要 Milvus 就绪：{exc}")

    embedded = db_session.scalars(
        select(KnowledgePoint).where(KnowledgePoint.embedding_status == 1)
    ).all()
    missing = [
        kp.id
        for kp in embedded
        if indexer.count(f'pk == "kp_{kp.id}"') == 0
    ]
    assert not missing, f"知识点已标记向量化但 Milvus 缺失：{missing}"
