"""通道 B · 关键词检索（MySQL ngram FULLTEXT，docs/05 §3.2）。

兜底：ngram 对 <2 字查询或特殊符号可能零命中，此时降级为 LIKE 逐词 OR，
并记录降级比例（> 30% 说明分词策略需调整，docs/05 §3.2）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from loguru import logger
from sqlalchemy import bindparam, text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.query_rewriter import QueryInfo
from app.rag.types import RetrievedItem

#: 降级统计（进程内，运维观察用）
_fallback_stats = {"total": 0, "fallback": 0}

# 切片通道：ngram 全文检索 + 文档元数据 join
CHUNK_SQL = sql_text(
    """
    SELECT c.id AS source_id, c.document_id, c.kb_id, c.article_no, c.page_start AS page_no,
           c.chunk_index, c.content, c.raw_content,
           d.title AS doc_title, d.doc_no, d.issuing_authority, d.timeliness, d.category,
           YEAR(d.publish_date) AS publish_year,
           MATCH(c.content) AGAINST (:q IN NATURAL LANGUAGE MODE) AS score
    FROM document_chunk c
    JOIN document d ON d.id = c.document_id
    WHERE MATCH(c.content) AGAINST (:q IN NATURAL LANGUAGE MODE)
      AND d.status != 'archived'
      {kb_filter}
    ORDER BY score DESC
    LIMIT :limit
    """
)

# 知识点通道：title + content + keywords 权重更高，标题精确命中额外 +5
KP_SQL = sql_text(
    """
    SELECT k.id AS source_id, k.primary_document_id AS document_id, k.kb_id,
           k.article_no, k.title, k.content, k.doc_no, k.issuing_authority,
           k.timeliness, k.category, k.primary_chunk_id,
           YEAR(k.effective_date) AS publish_year,
           MATCH(k.title, k.content, k.keywords) AGAINST (:q IN NATURAL LANGUAGE MODE)
           + IF(k.title LIKE CONCAT('%', :raw, '%'), 5, 0) AS score
    FROM knowledge_point k
    WHERE k.status = 'published'
      AND k.verify_status = 'passed'
      AND MATCH(k.title, k.content, k.keywords) AGAINST (:q IN NATURAL LANGUAGE MODE)
      {kb_filter}
    ORDER BY score DESC
    LIMIT :limit
    """
)

# 结构化线索精确匹配（条号/文号命中直接置顶，docs/05 §2.1）
CLUE_CHUNK_SQL = sql_text(
    """
    SELECT c.id AS source_id, c.document_id, c.kb_id, c.article_no, c.page_start AS page_no,
           c.chunk_index, c.content, c.raw_content,
           d.title AS doc_title, d.doc_no, d.issuing_authority, d.timeliness, d.category,
           YEAR(d.publish_date) AS publish_year, 100.0 AS score
    FROM document_chunk c
    JOIN document d ON d.id = c.document_id
    WHERE (c.article_no IN :article_nos OR d.doc_no IN :doc_nos)
      AND d.status != 'archived'
      {kb_filter}
    LIMIT :limit
    """
)

# LIKE 兜底（逐词 OR）
LIKE_CHUNK_SQL = sql_text(
    """
    SELECT c.id AS source_id, c.document_id, c.kb_id, c.article_no, c.page_start AS page_no,
           c.chunk_index, c.content, c.raw_content,
           d.title AS doc_title, d.doc_no, d.issuing_authority, d.timeliness, d.category,
           YEAR(d.publish_date) AS publish_year, 1.0 AS score
    FROM document_chunk c
    JOIN document d ON d.id = c.document_id
    WHERE ({like_cond})
      AND d.status != 'archived'
      {kb_filter}
    LIMIT :limit
    """
)


def _kb_filter(kb_ids: Optional[Sequence[int]]) -> tuple[str, dict]:
    if not kb_ids:
        return "", {}
    marks = ",".join(f":kb{i}" for i in range(len(kb_ids)))
    params = {f"kb{i}": int(k) for i, k in enumerate(kb_ids)}
    return f" AND c.kb_id IN ({marks})", params


def _kb_filter_kp(kb_ids: Optional[Sequence[int]]) -> tuple[str, dict]:
    if not kb_ids:
        return "", {}
    marks = ",".join(f":kb{i}" for i in range(len(kb_ids)))
    params = {f"kb{i}": int(k) for i, k in enumerate(kb_ids)}
    return f" AND k.kb_id IN ({marks})", params


def _row_to_chunk_item(row: Any, rank: int) -> RetrievedItem:
    return RetrievedItem(
        source_type="chunk",
        source_id=int(row.source_id),
        kb_id=int(row.kb_id or 0),
        document_id=int(row.document_id or 0),
        category=row.category or "",
        timeliness=row.timeliness or "unknown",
        article_no=row.article_no,
        page_no=int(row.page_no) if row.page_no else None,
        chunk_index=int(row.chunk_index or -1),
        content=row.content or "",
        raw_content=row.raw_content or "",
        doc_title=getattr(row, "doc_title", None),
        doc_no=row.doc_no,
        issuing_authority=row.issuing_authority,
        publish_year=int(row.publish_year or 0),
        keyword_rank=rank,
    )


def _row_to_kp_item(row: Any, rank: int) -> RetrievedItem:
    return RetrievedItem(
        source_type="knowledge_point",
        source_id=int(row.source_id),
        kb_id=int(row.kb_id or 0),
        document_id=int(row.document_id or 0),
        category=row.category or "",
        timeliness=row.timeliness or "unknown",
        article_no=row.article_no,
        page_no=None,
        chunk_index=-1,
        content=row.content or "",
        raw_content=row.content or "",
        title=row.title,
        doc_title=row.doc_title,
        doc_no=row.doc_no,
        issuing_authority=row.issuing_authority,
        publish_year=int(row.publish_year or 0),
        keyword_rank=rank,
    )


def search_keyword(
    db: Session,
    query_info: QueryInfo,
    kb_ids: Optional[Sequence[int]] = None,
    top_k: Optional[int] = None,
) -> List[RetrievedItem]:
    """关键词检索：FULLTEXT(ngram) 两路 + 结构化线索置顶 + LIKE 兜底。"""
    limit = top_k or settings.keyword_top_k
    q = query_info.keyword_query
    raw = query_info.cleaned
    items: List[RetrievedItem] = []

    # 1) 结构化线索精确匹配（条号/文号），命中置顶（融合阶段 ×1.5）
    if query_info.has_structured_clue:
        items.extend(_clue_search(db, query_info, kb_ids, limit))

    # 2) FULLTEXT 主通道
    kb_sql, kb_params = _kb_filter(kb_ids)
    chunk_rows = db.execute(
        sql_text(CHUNK_SQL.text.format(kb_filter=kb_sql)),
        {"q": q, "limit": limit, **kb_params},
    ).fetchall()
    kp_sql, kp_params = _kb_filter_kp(kb_ids)
    kp_rows = db.execute(
        sql_text(KP_SQL.text.format(kb_filter=kp_sql)),
        {"q": q, "raw": raw, "limit": limit, **kp_params},
    ).fetchall()

    fulltext_hits = [_row_to_chunk_item(r, i) for i, r in enumerate(chunk_rows, 1)]
    fulltext_hits += [_row_to_kp_item(r, i) for i, r in enumerate(kp_rows, 1)]

    # 3) 兜底：FULLTEXT 零命中 → LIKE 逐词 OR
    _fallback_stats["total"] += 1
    if not fulltext_hits:
        _fallback_stats["fallback"] += 1
        fulltext_hits = _like_fallback(db, query_info, kb_ids, limit)
        ratio = _fallback_stats["fallback"] / max(1, _fallback_stats["total"])
        logger.info(
            "关键词检索降级 LIKE（降级比例 {:.0%}）", ratio
        )
        if ratio > 0.3:
            logger.warning("关键词检索降级比例 > 30%，分词策略需要调整")

    items.extend(fulltext_hits)

    # 按唯一键去重（线索命中优先保留）
    seen: dict[str, RetrievedItem] = {}
    for it in items:
        if it.key not in seen:
            seen[it.key] = it
    merged = list(seen.values())
    for i, it in enumerate(merged, 1):
        it.keyword_rank = i
    return merged


def _clue_search(
    db: Session,
    query_info: QueryInfo,
    kb_ids: Optional[Sequence[int]],
    limit: int,
) -> List[RetrievedItem]:
    article_nos = query_info.article_nos or [""]
    doc_nos = query_info.doc_nos or [""]
    kb_sql, kb_params = _kb_filter(kb_ids)
    rows = db.execute(
        sql_text(CLUE_CHUNK_SQL.text.format(kb_filter=kb_sql)).bindparams(
            bindparam("article_nos", expanding=True), bindparam("doc_nos", expanding=True)),
        {
            "article_nos": tuple(article_nos),
            "doc_nos": tuple(doc_nos),
            "limit": limit,
            **kb_params,
        },
    ).fetchall()
    return [_row_to_chunk_item(r, i) for i, r in enumerate(rows, 1)]


def _like_fallback(
    db: Session,
    query_info: QueryInfo,
    kb_ids: Optional[Sequence[int]],
    limit: int,
) -> List[RetrievedItem]:
    words = [w for w in query_info.keywords if len(w) >= 1][:8] or [query_info.cleaned]
    conds = []
    params: Dict[str, Any] = {"limit": limit}
    for i, w in enumerate(words):
        conds.append(f"c.content LIKE :w{i}")
        params[f"w{i}"] = f"%{w}%"
    kb_sql, kb_params = _kb_filter(kb_ids)
    params.update(kb_params)
    rows = db.execute(
        sql_text(LIKE_CHUNK_SQL.text.format(like_cond=" OR ".join(conds), kb_filter=kb_sql)),
        params,
    ).fetchall()
    return [_row_to_chunk_item(r, i) for i, r in enumerate(rows, 1)]


def fallback_ratio() -> float:
    return _fallback_stats["fallback"] / max(1, _fallback_stats["total"])
