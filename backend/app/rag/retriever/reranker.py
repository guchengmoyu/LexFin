"""重排 Reranker（docs/05 §4）。

一期：PassthroughReranker —— 按融合分排序直接截断 Top-5（RERANK_ENABLED=false，ADR-05）；
二期：BgeReranker —— bge-reranker-base CrossEncoder 精排，接口已冻结。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from loguru import logger

from app.core.config import settings
from app.rag.types import RetrievedItem


class PassthroughReranker:
    """按融合分数截断，不改变顺序。"""

    def rerank(
        self, query: str, items: Sequence[RetrievedItem], top_n: Optional[int] = None
    ) -> List[RetrievedItem]:
        limit = top_n or settings.final_top_n
        return list(items)[:limit]


class BgeReranker:
    """二期：BAAI/bge-reranker-base CrossEncoder 精排（docs/05 §4）。"""

    def __init__(self, model_name: Optional[str] = None) -> None:
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name or settings.rerank_model, max_length=512)

    def rerank(
        self, query: str, items: Sequence[RetrievedItem], top_n: Optional[int] = None
    ) -> List[Tuple[RetrievedItem, float]]:
        import numpy as np

        limit = top_n or settings.rerank_top_n
        if not items:
            return []
        pairs = [(query, it.content_for_rerank) for it in items]
        scores = self.model.predict(pairs)
        probs = 1 / (1 + np.exp(-scores))
        ranked = sorted(zip(items, probs), key=lambda x: -float(x[1]))
        return [
            (it, float(p))
            for it, p in ranked[:limit]
            if float(p) >= settings.rerank_min_score
        ]


_reranker = None


def get_reranker():
    """按 RERANK_ENABLED 装配；开启但模型加载失败时降级 Passthrough（不阻断问答）。"""
    global _reranker
    if _reranker is not None:
        return _reranker
    if settings.rerank_enabled:
        try:
            _reranker = BgeReranker()
            logger.info("重排模型已启用 {}", settings.rerank_model)
            return _reranker
        except Exception as exc:
            logger.warning("重排模型加载失败，降级为按分截断: {}", exc)
    _reranker = PassthroughReranker()
    return _reranker


def rerank(query: str, items: Sequence[RetrievedItem], top_n: Optional[int] = None) -> List[RetrievedItem]:
    """统一入口：返回重排后的条目（BgeReranker 模式下丢弃低于阈值的条目）。"""
    engine = get_reranker()
    result = engine.rerank(query, items, top_n)
    if result and isinstance(result[0], tuple):
        return [it for it, _ in result]
    return list(result)  # type: ignore[arg-type]
