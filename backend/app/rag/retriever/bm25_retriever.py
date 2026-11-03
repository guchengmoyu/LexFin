"""通道 B（关键词）的 BM25 实现：Milvus 2.5 原生全文检索（docs/05 §3.2.1）。

与 `keyword_retriever.search_keyword`（MySQL ngram FULLTEXT）保持同一语义：
- 输入 QueryInfo，用 `keyword_query`（已做口语→术语归一）作为检索串；
- 查询里带条号/文号线索时，先用标量条件精确取行并置顶（对应 MySQL 版的 `_clue_search`）；
- 返回 RetrievedItem 列表，`keyword_rank` 从 1 开始连续编号。
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, List, Optional, Sequence

from loguru import logger

from app.core.config import settings
from app.db import milvus_bm25
from app.rag.types import RetrievedItem

if TYPE_CHECKING:  # pragma: no cover
    from app.rag.query_rewriter import QueryInfo


def _to_item(row: dict, rank: int) -> RetrievedItem:
    content = row.get("content") or ""
    return RetrievedItem(
        source_type=row.get("source_type") or "chunk",
        source_id=int(row.get("source_id") or 0),
        kb_id=int(row.get("kb_id") or 0),
        document_id=int(row.get("document_id") or 0),
        category=row.get("category") or "",
        timeliness=row.get("timeliness") or "unknown",
        article_no=row.get("article_no"),
        page_no=row.get("page_no"),
        chunk_index=int(row.get("chunk_index") or -1),
        content=content,
        raw_content=content,
        title=row.get("title"),
        doc_title=row.get("doc_title"),
        doc_no=row.get("doc_no"),
        issuing_authority=row.get("issuing_authority"),
        publish_year=int(row.get("publish_year") or 0),
        keyword_rank=rank,
        score=float(row.get("_score") or 0.0),
    )


def _kb_expr(kb_ids: Optional[Sequence[int]]) -> str:
    if not kb_ids:
        return ""
    ids = ",".join(str(int(k)) for k in kb_ids)
    return f"kb_id in [{ids}]"


def _clue_items(
    query_info: "QueryInfo", kb_ids: Optional[Sequence[int]], limit: int
) -> List[RetrievedItem]:
    """条号/文号线索命中置顶（与 keyword_retriever._clue_search 对齐）。"""
    arts = [a for a in (query_info.article_nos or []) if a]
    docs = [d for d in (query_info.doc_nos or []) if d]
    if not arts and not docs:
        return []
    parts = []
    if arts:
        parts.append(
            "article_no in [%s]" % ",".join(json.dumps(a, ensure_ascii=False) for a in arts)
        )
    if docs:
        parts.append(
            "doc_no in [%s]" % ",".join(json.dumps(d, ensure_ascii=False) for d in docs)
        )
    expr = " or ".join(parts)
    kb = _kb_expr(kb_ids)
    if kb:
        expr = f"({expr}) and {kb}"
    try:
        rows = milvus_bm25.query(expr, limit=limit)
    except Exception as exc:  # pragma: no cover - 依赖外部服务
        logger.warning("BM25 线索检索失败（已跳过）：{}", exc)
        return []
    return [_to_item(row, rank) for rank, row in enumerate(rows, start=1)]


def search_bm25(
    query_info: "QueryInfo",
    kb_ids: Optional[Sequence[int]] = None,
    top_k: Optional[int] = None,
) -> List[RetrievedItem]:
    """BM25 检索；Milvus 不可用或集合缺失时返回空列表（由上层决定是否降级）。

    查询串两路并用、按秩融合（实测单用整句在无扩展时更好，单用关键词串在有扩展时更好）：
    ① 整句（口语→术语归一后）：BM25 对长句的饱和与长度归一能压住泛词；
    ② keyword_query 关键词串：扩展出来的检索式更偏短语，词串匹配更集中。
    """
    if settings.keyword_backend != "bm25" and settings.keyword_backend != "both":
        return []
    limit = int(top_k or settings.keyword_top_k)
    clues = _clue_items(query_info, kb_ids, limit)

    natural = (query_info.effective_query or query_info.cleaned or "").strip()
    if natural and getattr(settings, "synonym_enabled", False):
        from app.rag.synonyms import apply_synonyms

        natural = apply_synonyms(natural, append=settings.synonym_append_terms)
    keyword_text = (query_info.keyword_query or "").strip()
    texts: List[str] = []
    for t in (natural, keyword_text):
        if t and t not in texts:
            texts.append(t)
    if not texts:
        return clues

    seen = {f"{i.source_type}_{i.source_id}" for i in clues}
    scores: dict = {}
    pool: dict = {}
    for text in texts:
        try:
            rows = milvus_bm25.search(
                text,
                limit=limit,
                expr=_kb_expr(kb_ids) or None,
                output_fields=milvus_bm25.OUTPUT_FIELDS,
            )
        except Exception as exc:  # 集合缺失/服务不可用时不让整条链路失败
            logger.warning("BM25 检索失败，本路返回空：{}", exc)
            continue
        for rank, row in enumerate(rows, start=1):
            item = _to_item(row, 0)
            key = f"{item.source_type}_{item.source_id}"
            if key in seen:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (settings.rrf_k + rank)
            pool.setdefault(key, item)

    items: List[RetrievedItem] = list(clues)
    for key, item in sorted(pool.items(), key=lambda kv: scores.get(kv[0], 0.0), reverse=True):
        items.append(item)
    for rank, item in enumerate(items, start=1):
        item.keyword_rank = rank
    return items[:limit]
