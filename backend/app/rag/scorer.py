"""可信度评分（docs/05 §9）。

confidence = 0.40×s1 + 0.25×s2 + 0.20×s3 + 0.15×s4
  s1 = 归一化 Top-1 融合分 = min(1, rrf_top1 / RRF_REF)
  s2 = 引用覆盖率 = 含角标句子数 / 答案总句子数
  s3 = Top-5 平均融合分归一化 = min(1, mean(rrf_top5) / RRF_REF)
  s4 = 时效因子 = 被引用条目中 effective 的占比

注意：confidence 是工程启发式指标，用于引导用户复核，
不得对外宣称是「准确率」（85% 指标由人工评测独立得出）。
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.core.config import settings
from app.core.constants import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
from app.rag.citation import cited_ratio
from app.rag.types import Citation

RRF_REF_FALLBACK = 0.03


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score(
    answer: str,
    citations: Sequence[Citation],
    fusion_scores: Sequence[float],
    used_citations: Optional[Sequence[Citation]] = None,
) -> float:
    """计算可信度 0~1。无任何引用时直接判 0（docs/05 §9）。"""
    cited = list(used_citations if used_citations is not None else citations)
    if not cited:
        return 0.0

    rrf_ref = settings.rrf_ref or RRF_REF_FALLBACK
    scores = [float(s) for s in fusion_scores if s is not None]
    top1 = max(scores) if scores else 0.0
    mean_top = (sum(scores) / len(scores)) if scores else 0.0

    s1 = _clamp(top1 / rrf_ref)
    s2 = _clamp(cited_ratio(answer))
    s3 = _clamp(mean_top / rrf_ref)
    s4 = _clamp(
        sum(1 for c in cited if (c.timeliness or "unknown") == "effective") / len(cited)
    )

    confidence = 0.40 * s1 + 0.25 * s2 + 0.20 * s3 + 0.15 * s4
    return round(_clamp(confidence), 3)


def level(confidence: float) -> str:
    """分级：high ≥0.80 / medium 0.60~0.80（闭区间下界）/ low <0.60。"""
    if confidence >= CONFIDENCE_HIGH:
        return "high"
    if confidence >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


def level_label(confidence_level: str) -> str:
    return {"high": "可信度高", "medium": "可信度中", "low": "可信度低，建议核对原文"}.get(
        confidence_level, "可信度低，建议核对原文"
    )
