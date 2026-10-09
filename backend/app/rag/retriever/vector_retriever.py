"""通道 A · 向量语义检索（docs/05 §3.1）。"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.core.config import settings
from app.rag.embedder import encode_query
from app.rag.indexer import build_filter, indexer, row_to_item
from app.rag.types import RetrievedItem


def search_vector(
    query: str,
    kb_ids: Optional[Sequence[int]] = None,
    categories: Optional[Sequence[str]] = None,
    timeliness: Optional[Sequence[str]] = None,
    source_types: Optional[Sequence[str]] = None,
    top_k: Optional[int] = None,
) -> List[RetrievedItem]:
    """查询向量化 + Milvus HNSW/COSINE 检索，返回带 vector_rank 的候选集。"""
    limit = top_k or settings.vector_top_k
    vector = encode_query(query)
    expr = build_filter(kb_ids, categories, timeliness, source_types)
    rows = indexer.search(vector=vector, expr=expr, limit=limit)
    items: List[RetrievedItem] = []
    for rank, row in enumerate(rows, start=1):
        item = row_to_item(row)
        item.vector_rank = rank
        items.append(item)
    return items
