"""通用文本工具：全半角归一、HTML 转义、句子切分、相似度判定。"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import Iterable, List

#: 页码占位行（docs/04 §5：清洗时删除，切分前保留 offset→page 映射）
PAGE_NUMBER_RE = re.compile(r"^[-—\s]*\d+[-—\s]*$")

#: 中文句末标点
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")


def normalize_text(text: str) -> str:
    """NFKC 归一（全角数字/字母/括号/百分号转半角，保留中文标点）。"""
    return unicodedata.normalize("NFKC", text or "")


def strip_invisible(text: str) -> str:
    """删除控制字符与常见 OCR 噪声字符（docs/04 §5）。"""
    return re.sub(r"[\x00-\x08\x0b-\x1f\u200b\ufeff]", "", text or "")


def collapse_whitespace(text: str) -> str:
    """连续空格/Tab → 单空格；连续 ≥2 换行 → 1 换行。"""
    text = re.sub(r"[ \t\u3000]+", " ", text or "")
    text = re.sub(r"\n{2,}", "\n", text)
    return text


def escape_html(text: str) -> str:
    """HTML 转义（/search 高亮前必须先转义再插入 <em>，防 XSS，docs/06 §6）。"""
    return html.escape(text or "", quote=True)


def split_sentences(text: str) -> List[str]:
    """按中文句末标点切句（可信度评分 s2 的分母/分子需要）。"""
    parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(text or "")]
    return [p for p in parts if p]


def ngram_jaccard(a: str, b: str, n: int = 3) -> float:
    """3-gram Jaccard 相似度，用于检索去重（docs/05 §3.4 阈值 0.95）。"""
    if not a or not b:
        return 0.0
    ga = {a[i : i + n] for i in range(max(0, len(a) - n + 1))}
    gb = {b[i : i + n] for i in range(max(0, len(b) - n + 1))}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def is_page_number_line(line: str) -> bool:
    return bool(PAGE_NUMBER_RE.match((line or "").strip()))


def truncate(text: str, limit: int, ellipsis: str = "……") -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(ellipsis))] + ellipsis


def first_non_empty_lines(text: str, n: int) -> List[str]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    out: List[str] = [ln for ln in lines if ln][:n]
    return out
