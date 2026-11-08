"""答案溯源 · 角标解析与校验（docs/05 §8 ★核心差异化）。

只落库答案真正使用的引用；越界角标必须记录日志并计入质量指标
（发生率 > 5% 说明 Prompt 需要调整）。
"""
from __future__ import annotations

import re
from typing import List, Sequence, Set

from loguru import logger

from app.rag.types import Citation, RetrievedItem

#: Prompt 约束为半角 [n]；全角【n】不匹配（docs/09 §3.3 test_citation）
CITE_PATTERN = re.compile(r"\[(\d{1,2})\]")

# 越界引用统计（进程内，质量观察用）
_out_of_range_stats = {"total_answers": 0, "answers_with_invalid": 0}


def extract_cite_indexes(answer: str) -> Set[int]:
    """解析答案中出现的角标序号（[01] 前导零 → 1）。"""
    return {int(m) for m in CITE_PATTERN.findall(answer or "")}


def resolve(answer: str, citations: Sequence[Citation]) -> List[Citation]:
    """过滤越界角标，只返回答案真正使用的引用（保持 cite_index 升序）。"""
    used = extract_cite_indexes(answer)
    valid = {c.cite_index for c in citations}

    _out_of_range_stats["total_answers"] += 1
    invalid = used - valid
    if invalid:
        _out_of_range_stats["answers_with_invalid"] += 1
        logger.warning("LLM 输出越界引用 {}，已过滤", sorted(invalid))

    used_valid = used & valid
    return sorted(
        (c for c in citations if c.cite_index in used_valid),
        key=lambda c: c.cite_index,
    )


def build_citations(items: Sequence[RetrievedItem]) -> List[Citation]:
    """Top-N 证据 → 编号引用列表（检索完成即下发，docs/05 §8.1）。"""
    return [Citation.from_item(item, cite_index=i) for i, item in enumerate(items, start=1)]


def cited_ratio(answer: str) -> float:
    """答案中含角标句子占比（可信度 s2 的输入）。"""
    from app.utils.text import split_sentences

    sentences = split_sentences(answer or "")
    if not sentences:
        return 0.0
    hit = sum(1 for s in sentences if CITE_PATTERN.search(s))
    return hit / len(sentences)


def out_of_range_ratio() -> float:
    total = _out_of_range_stats["total_answers"]
    return _out_of_range_stats["answers_with_invalid"] / total if total else 0.0
