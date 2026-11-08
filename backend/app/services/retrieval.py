"""检索服务（docs/06 §5.7）：/retrieve 混合检索 + /search 关键词检索（无 LLM，低时延）。"""
from __future__ import annotations

import time
from typing import List, Optional, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.response import paged
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.models.knowledge_point import KnowledgePoint
from app.rag.query_rewriter import analyze
from app.rag.retriever.hybrid_retriever import hybrid_retriever
from app.rag.types import RetrievedItem
from app.utils.text import escape_html


def highlight_text(text: str, keywords: Sequence[str]) -> str:
    """高亮命中词：先 HTML 转义再插入 <em>（防 XSS，docs/06 §6）。"""
    escaped = escape_html(text or "")
    for kw in keywords:
        if not kw:
            continue
        safe_kw = escape_html(kw)
        escaped = escaped.replace(safe_kw, f"<em>{safe_kw}</em>")
    return escaped


class RetrievalService:
    async def retrieve(self, db: Session, payload: dict) -> dict:
        t0 = time.perf_counter()
        query_info = analyze(payload["query"])
        items = await hybrid_retriever.retrieve(
            db,
            query_info,
            mode=payload.get("mode") or "hybrid",
            kb_ids=payload.get("kb_ids"),
            categories=payload.get("categories"),
            timeliness=payload.get("timeliness"),
            include_knowledge_points=payload.get("include_knowledge_points", True),
            include_chunks=payload.get("include_chunks", True),
            top_k=payload.get("top_k") or 10,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "query": payload["query"],
            "mode": payload.get("mode") or "hybrid",
            "latency_ms": latency_ms,
            "total": len(items),
            "items": [
                self._item_dict(rank, item, query_info.keywords, highlight=False)
                for rank, item in enumerate(items, start=1)
            ],
        }

    async def search(
        self,
        db: Session,
        q: str,
        kb_id: Optional[int] = None,
        page: int = 1,
        size: int = 10,
        mode: str = "keyword",
        highlight: bool = True,
        category: Optional[str] = None,
        timeliness: Optional[str] = None,
    ) -> dict:
        """关键词检索便捷版：分页浏览，供「关键词检索」页面（P95 ≤ 500ms，无 LLM）。"""
        t0 = time.perf_counter()
        query_info = analyze(q)
        items = await hybrid_retriever.retrieve(
            db,
            query_info,
            mode=mode,
            kb_ids=[kb_id] if kb_id else None,
            categories=[category] if category else None,
            timeliness=[timeliness] if timeliness else None,
            top_k=100,  # 取足够候选再分页
        )
        total = len(items)
        start = (page - 1) * size
        page_items = items[start : start + size]
        return {
            **paged(total, page, size, [
                self._item_dict(start + rank, item, query_info.keywords, highlight)
                for rank, item in enumerate(page_items, start=1)
            ]),
            "query": q,
            "mode": mode,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    @staticmethod
    def _item_dict(
        rank: int, item: RetrievedItem, keywords: Sequence[str], highlight: bool
    ) -> dict:
        snippet = (item.raw_content or item.content or "").replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "……"
        return {
            "rank": rank,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "title": item.title,
            "snippet": snippet,
            "highlight": highlight_text(snippet, keywords) if highlight else None,
            "document_id": item.document_id,
            "doc_title": item.doc_title,
            "doc_no": item.doc_no,
            "issuing_authority": item.issuing_authority,
            "article_no": item.article_no,
            "page_no": item.page_no,
            "timeliness": item.timeliness,
            "score": round(float(item.score), 5),
            "vector_rank": item.vector_rank,
            "keyword_rank": item.keyword_rank,
        }


retrieval_service = RetrievalService()
