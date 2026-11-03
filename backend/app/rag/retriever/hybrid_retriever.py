"""混合融合 · 加权 RRF + 去重 + 时效加权（docs/05 §3.3/§3.4 ★核心）。

RRF 不依赖两路分数量纲，是工程上最稳健的融合方式；
`rrf_fuse` 为纯函数，便于单元测试与网格调参（docs/05 §13）。
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Sequence, Set

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.query_rewriter import QueryInfo
from app.rag.retriever.keyword_retriever import search_keyword
from app.rag.retriever.vector_retriever import search_vector
from app.rag.types import RetrievedItem
from app.utils.text import ngram_jaccard


def _keyword_channel(db, query_info, kb_ids=None) -> List[RetrievedItem]:
    """关键词通道按 settings.keyword_backend 分流（docs/05 §3.2.1）。

    mysql：ngram FULLTEXT（旧实现，保留可回切）；
    bm25：Milvus 2.5 原生 BM25；
    both：两路都跑，按秩融合（便于排列组合实验）。
    """
    backend = getattr(settings, "keyword_backend", "mysql")
    if backend == "mysql":
        return search_keyword(db, query_info, kb_ids)

    from app.rag.retriever.bm25_retriever import search_bm25

    bm25_items = search_bm25(query_info, kb_ids)
    if backend == "bm25":
        return bm25_items
    # both：两路按秩公平融合（各取 1/(k+rank)），保留连续 keyword_rank
    mysql_items = search_keyword(db, query_info, kb_ids)
    scores = {}
    for items in (bm25_items, mysql_items):
        for rank, item in enumerate(items, start=1):
            key = f"{item.source_type}_{item.source_id}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (settings.rrf_k + rank)
    pool = {f"{i.source_type}_{i.source_id}": i for i in mysql_items}
    pool.update({f"{i.source_type}_{i.source_id}": i for i in bm25_items})
    merged = sorted(pool.items(), key=lambda kv: scores.get(kv[0], 0.0), reverse=True)
    out = []
    for rank, (_key, item) in enumerate(merged, start=1):
        item.keyword_rank = rank
        out.append(item)
    return out

# 结构化线索精确命中加权（docs/05 §3.3）
CLUE_BOOST = 1.5
# 知识点优先（人工校验过的高质量资产）
KP_BOOST = 1.15
# 内容相似度去重阈值（3-gram Jaccard）
SIMILARITY_THRESHOLD = 0.95
# 同 document_id + article_no 最多保留块数
MAX_SAME_ARTICLE = 2


# --------------------------------------------------------------------------- #
#  RRF 融合（纯函数）
# --------------------------------------------------------------------------- #
def rrf_fuse(
    vector_items: Sequence[RetrievedItem],
    keyword_items: Sequence[RetrievedItem],
    *,
    rrf_k: Optional[int] = None,
    w_vector: Optional[float] = None,
    w_keyword: Optional[float] = None,
    timeliness_weights: Optional[Dict[str, float]] = None,
    query_article_nos: Optional[Sequence[str]] = None,
    query_doc_nos: Optional[Sequence[str]] = None,
) -> List[RetrievedItem]:
    """加权 RRF：score += W / (K + rank)，再乘时效权重与结构化/知识点加权。"""
    k = rrf_k if rrf_k is not None else settings.rrf_k
    wv = w_vector if w_vector is not None else settings.rrf_w_vector
    wk = w_keyword if w_keyword is not None else settings.rrf_w_keyword
    return rrf_fuse_multi(
        [(vector_items, wv), (keyword_items, wk)],
        rrf_k=k,
        timeliness_weights=timeliness_weights,
        query_article_nos=query_article_nos,
        query_doc_nos=query_doc_nos,
    )


def rrf_fuse_multi(
    channels: Sequence[tuple],
    *,
    rrf_k: Optional[int] = None,
    timeliness_weights: Optional[Dict[str, float]] = None,
    query_article_nos: Optional[Sequence[str]] = None,
    query_doc_nos: Optional[Sequence[str]] = None,
) -> List[RetrievedItem]:
    """多路加权 RRF（docs/05 §2.4）：channels = [(items, 权重), ...]。

    检索式扩展后，原问题与各扩展式各自有向量/关键词通道，
    用不同权重（原问题最高）做一次统一融合，避免多路结果互相覆盖。
    """
    k = rrf_k if rrf_k is not None else settings.rrf_k
    tw = timeliness_weights or settings.timeliness_weights
    article_nos: Set[str] = set(query_article_nos or [])
    doc_nos: Set[str] = set(query_doc_nos or [])

    fused: Dict[str, RetrievedItem] = {}
    scores: Dict[str, float] = {}

    def _add(item: RetrievedItem, weight: float, rank: int) -> None:
        key = item.key
        if key not in fused:
            # 拷贝，避免污染通道产物
            clone = RetrievedItem(**{**item.__dict__})
            fused[key] = clone
        # Merge channel metadata as well as scores; keyword evidence must not
        # disappear when the vector channel creates the clone first.
        if item.vector_rank is not None:
            fused[key].vector_rank = item.vector_rank
        if item.keyword_rank is not None:
            fused[key].keyword_rank = item.keyword_rank
        if item.vector_similarity is not None:
            fused[key].vector_similarity = item.vector_similarity
        scores[key] = scores.get(key, 0.0) + weight / (k + rank)

    for items, weight in channels:
        for rank, item in enumerate(items or [], start=1):
            _add(item, weight, rank)

    result: List[RetrievedItem] = []
    for key, item in fused.items():
        final = scores[key]
        # 时效加权（docs/03 §4.4）
        final *= tw.get(item.timeliness or "unknown", 1.0)
        # 结构化线索加分（docs/05 §2.1）：文号抽取可能带前导/残缺，
        # 双向包含匹配保证「银保监会令2018年第3号」这类精确命中也能加权
        if item.article_no and item.article_no in article_nos:
            final *= CLUE_BOOST
        if item.doc_no and any(
            item.doc_no in d or (d and d in item.doc_no) for d in doc_nos
        ):
            final *= CLUE_BOOST
        # 知识点优先
        if item.source_type == "knowledge_point":
            final *= KP_BOOST
        item.score = final
        result.append(item)

    # 排序：分数降序；同分时按 source_type 与 source_id 稳定排序
    result.sort(key=lambda x: (-x.score, x.source_type, x.source_id))
    return result


# --------------------------------------------------------------------------- #
#  去重（docs/05 §3.4，ADR-09 的落地）
# --------------------------------------------------------------------------- #
def dedup_items(
    items: Sequence[RetrievedItem],
    kp_primary_chunk_ids: Optional[Dict[int, int]] = None,
) -> List[RetrievedItem]:
    """1) 知识点与其 primary_chunk 同时命中 → 保留知识点；
    2) 同 document_id + article_no 的滑窗块最多保留 2 个且须相邻；
    3) 内容相似度 > 0.95 → 保留高分者。
    """
    kp_primary_chunk_ids = kp_primary_chunk_ids or {}
    # 1) 知识点优先
    kp_chunk_ids: Set[int] = set(kp_primary_chunk_ids.values())
    kept: List[RetrievedItem] = []
    for item in items:
        if item.source_type == "chunk" and item.source_id in kp_chunk_ids:
            continue
        kept.append(item)

    # 2) 同 document + article 限流（按分数顺序保留相邻块）
    by_article: Dict[tuple, List[RetrievedItem]] = {}
    out: List[RetrievedItem] = []
    for item in kept:
        if item.source_type != "chunk" or not item.article_no:
            out.append(item)
            continue
        bucket_key = (item.document_id, item.article_no)
        bucket = by_article.setdefault(bucket_key, [])
        if len(bucket) < MAX_SAME_ARTICLE:
            bucket.append(item)
            out.append(item)
        elif all(
            abs((item.chunk_index or -1) - (b.chunk_index or -1)) == 1 for b in bucket
        ) and all(
            abs((b.chunk_index or -1) - (item.chunk_index or -1)) == 1 for b in bucket
        ):
            # 已达上限但相邻 → 仍丢弃（最多 2 个），仅记录相邻性用于日志
            pass

    # 3) 相似内容去重（3-gram Jaccard > 0.95 保留高分）
    final: List[RetrievedItem] = []
    for item in out:
        text_i = item.raw_content or item.content
        if any(
            ngram_jaccard(text_i, f.raw_content or f.content) > SIMILARITY_THRESHOLD
            for f in final
        ):
            continue
        final.append(item)
    return final


# --------------------------------------------------------------------------- #
#  混合检索编排（两通道并行，docs/05 §10）
# --------------------------------------------------------------------------- #
class HybridRetriever:
    async def retrieve(
        self,
        db: Session,
        query_info: QueryInfo,
        mode: str = "hybrid",
        kb_ids: Optional[Sequence[int]] = None,
        categories: Optional[Sequence[str]] = None,
        timeliness: Optional[Sequence[str]] = None,
        include_knowledge_points: bool = True,
        include_chunks: bool = True,
        top_k: Optional[int] = None,
    ) -> List[RetrievedItem]:
        source_types = []
        if include_chunks:
            source_types.append("chunk")
        if include_knowledge_points:
            source_types.append("knowledge_point")
        if not source_types:
            source_types = ["chunk", "knowledge_point"]

        query = query_info.effective_query
        vector_items: List[RetrievedItem] = []
        keyword_items: List[RetrievedItem] = []

        if mode in ("hybrid", "vector"):
            vector_items = await asyncio.to_thread(
                search_vector, query, kb_ids, categories, timeliness, source_types
            )
        if mode in ("hybrid", "keyword"):
            keyword_items = await asyncio.to_thread(
                _keyword_channel, db, query_info, kb_ids
            )
        vector_items = self._published_items(db, vector_items)
        keyword_items = self._published_items(db, keyword_items)
        # Milvus stores IDs and vector metadata; hydrate provenance from SQL
        # before fusion so structured document-number boosts also work.
        from sqlalchemy import select
        from app.models.document import Document
        doc_ids = {item.document_id for item in vector_items if item.document_id}
        documents = {doc.id: doc for doc in db.scalars(
            select(Document).where(Document.id.in_(doc_ids))
        ).all()} if doc_ids else {}
        for item in vector_items:
            doc = documents.get(item.document_id)
            if doc is not None:
                item.doc_title = doc.title
                item.doc_no = doc.doc_no
                item.issuing_authority = doc.issuing_authority
        if mode == "keyword":
            keyword_items = [i for i in keyword_items if i.source_type in source_types]
        if mode == "vector":
            vector_items = [i for i in vector_items if i.source_type in source_types]

        if mode == "hybrid":
            fused = rrf_fuse(
                vector_items,
                keyword_items,
                query_article_nos=query_info.article_nos,
                query_doc_nos=query_info.doc_nos,
            )
        elif mode == "vector":
            fused = vector_items
            for rank, it in enumerate(fused, 1):
                it.score = 1.0 / (settings.rrf_k + rank)
        else:  # keyword
            fused = keyword_items
            for rank, it in enumerate(fused, 1):
                it.score = 1.0 / (settings.rrf_k + rank)

        fused = [i for i in fused if i.source_type in source_types]
        deduped = dedup_items(fused, self._kp_primary_chunks(db, fused))
        limit = top_k or settings.final_top_n
        return deduped[:limit]

    async def retrieve_multi(
        self,
        db: Session,
        query_infos: Sequence[QueryInfo],
        *,
        mode: str = "hybrid",
        kb_ids: Optional[Sequence[int]] = None,
        categories: Optional[Sequence[str]] = None,
        timeliness: Optional[Sequence[str]] = None,
        include_knowledge_points: bool = True,
        include_chunks: bool = True,
        top_k: Optional[int] = None,
        variant_weights: Optional[Sequence[float]] = None,
    ) -> List[RetrievedItem]:
        """多查询召回（docs/05 §2.4）：原问题 + 检索式扩展各自双通道，再统一加权 RRF。

        约定：第一个 query_info 必须是最原始问题（权重最高，默认 1.0）；
        扩展式默认 query_expansion_weight（0.8）起逐条递减 0.15。
        单查询时直接退化为 retrieve()，保证行为完全一致。
        """
        infos = [qi for qi in query_infos if qi is not None]
        if not infos:
            return []
        if len(infos) == 1:
            return await self.retrieve(
                db, infos[0], mode=mode, kb_ids=kb_ids, categories=categories,
                timeliness=timeliness,
                include_knowledge_points=include_knowledge_points,
                include_chunks=include_chunks, top_k=top_k,
            )

        source_types = []
        if include_chunks:
            source_types.append("chunk")
        if include_knowledge_points:
            source_types.append("knowledge_point")
        if not source_types:
            source_types = ["chunk", "knowledge_point"]

        weights = list(variant_weights or [])
        while len(weights) < len(infos):
            i = len(weights)
            weights.append(
                1.0 if i == 0
                else max(0.3, settings.query_expansion_weight - 0.15 * (i - 1))
            )

        # 向量通道无 DB 依赖，可并行；关键词通道共用一个 Session，必须串行
        vec_lists: List[List[RetrievedItem]] = [[] for _ in infos]
        if mode in ("hybrid", "vector"):
            gathered = await asyncio.gather(*(
                asyncio.to_thread(
                    search_vector, info.effective_query, kb_ids, categories,
                    timeliness, source_types,
                )
                for info in infos
            ), return_exceptions=True)
            for idx, res in enumerate(gathered):
                if isinstance(res, Exception):
                    logger.warning("检索式扩展通道向量检索失败（已跳过）: {}", res)
                    continue
                vec_lists[idx] = list(res)
        kw_lists: List[List[RetrievedItem]] = [[] for _ in infos]
        if mode in ("hybrid", "keyword"):
            try:
                kw_lists = await asyncio.to_thread(
                    lambda: [_keyword_channel(db, info, kb_ids) for info in infos]
                )
            except Exception as exc:  # pragma: no cover - 依赖 DB
                logger.warning("检索式扩展通道关键词检索失败（已跳过）: {}", exc)

        channels: List[tuple] = []
        for weight, vec_items, kw_items in zip(weights, vec_lists, kw_lists):
            vec_items = [
                i for i in self._published_items(db, vec_items)
                if i.source_type in source_types
            ]
            kw_items = [
                i for i in self._published_items(db, kw_items)
                if i.source_type in source_types
            ]
            if mode in ("hybrid", "vector"):
                channels.append(
                    (self._hydrate_docs(db, vec_items), weight * settings.rrf_w_vector)
                )
            if mode in ("hybrid", "keyword"):
                channels.append(
                    (self._hydrate_docs(db, kw_items), weight * settings.rrf_w_keyword)
                )

        merged_articles: List[str] = []
        merged_docs: List[str] = []
        for info in infos:
            merged_articles.extend(info.article_nos or [])
            merged_docs.extend(info.doc_nos or [])
        fused = rrf_fuse_multi(
            channels,
            query_article_nos=merged_articles,
            query_doc_nos=merged_docs,
        )
        fused = [i for i in fused if i.source_type in source_types]
        deduped = dedup_items(fused, self._kp_primary_chunks(db, fused))
        limit = top_k or settings.final_top_n
        return deduped[:limit]

    @staticmethod
    def _hydrate_docs(db: Session, items: Sequence[RetrievedItem]) -> List[RetrievedItem]:
        """补全文档元数据（文号/机构），让结构化线索加权在融合阶段生效。"""
        if not items:
            return list(items)
        from sqlalchemy import select

        from app.models.document import Document

        doc_ids = {i.document_id for i in items if i.document_id}
        documents = {d.id: d for d in db.scalars(
            select(Document).where(Document.id.in_(doc_ids))
        ).all()} if doc_ids else {}
        for item in items:
            doc = documents.get(item.document_id)
            if doc is not None:
                item.doc_title = item.doc_title or doc.title
                item.doc_no = item.doc_no or doc.doc_no
                item.issuing_authority = item.issuing_authority or doc.issuing_authority
        return list(items)

    def retrieve_sync(self, *args, **kwargs) -> List[RetrievedItem]:
        return asyncio.run(self.retrieve(*args, **kwargs))

    @staticmethod
    def _published_items(db: Session, items: Sequence[RetrievedItem]) -> List[RetrievedItem]:
        from sqlalchemy import select
        from app.models.knowledge_point import KnowledgePoint
        from app.models.chunk import DocumentChunk
        from app.models.document import Document
        kp_ids = {item.source_id for item in items if item.source_type == "knowledge_point"}
        allowed = {kp.id: kp for kp in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_(kp_ids), KnowledgePoint.status == "published",
            KnowledgePoint.verify_status == "passed",
            KnowledgePoint.primary_chunk_id.is_not(None))).all()} if kp_ids else {}
        result = []
        for item in items:
            if item.source_type == "knowledge_point":
                kp = allowed.get(item.source_id)
                if kp is None:
                    continue
                chunk = db.get(DocumentChunk, kp.primary_chunk_id)
                doc = db.get(Document, kp.primary_document_id) if kp.primary_document_id else None
                if chunk is None or doc is None or doc.status != "ready":
                    continue
                item.title = kp.title
                item.raw_content = kp.content
                item.document_id = doc.id
                item.doc_title = doc.title
                item.doc_no = kp.doc_no or doc.doc_no
                item.issuing_authority = kp.issuing_authority or doc.issuing_authority
                item.page_no = chunk.page_start
                item.article_no = kp.article_no
            result.append(item)
        return result

    @staticmethod
    def _kp_primary_chunks(db: Session, items: Sequence[RetrievedItem]) -> Dict[int, int]:
        """知识点 → primary_chunk_id 映射（去重规则 1 需要）。"""
        from sqlalchemy import select

        from app.models.knowledge_point import KnowledgePoint

        kp_ids = [i.source_id for i in items if i.source_type == "knowledge_point"]
        if not kp_ids:
            return {}
        rows = db.execute(
            select(KnowledgePoint.id, KnowledgePoint.primary_chunk_id).where(
                KnowledgePoint.id.in_(kp_ids)
            )
        ).all()
        return {int(r[0]): int(r[1]) for r in rows if r[1]}


hybrid_retriever = HybridRetriever()
