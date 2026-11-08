"""元数据抽取（docs/04 §7，P1：为时效标注 FR-44 预留）。

抽取结果只作为「预填值」返回给前端表单，由上传人确认后再落库。
"""
from __future__ import annotations

import re
from typing import Optional

from app.utils.text import first_non_empty_lines

# 文号：兼容「银保监会令2018年第3号」「证监发〔2018〕12号」两种写法
DOC_NO_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,8}(?:令|公告|通知|发|字)?\s*[〔\[（(]\s*\d{4}\s*[〕\]）)]\s*第?\s*\d+\s*号"
    r"|[\u4e00-\u9fa5]{2,8}(?:令|公告|通知|发|字)\s*\d{4}\s*年?\s*第?\s*\d+\s*号"
)
DATE_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
EFFECTIVE_RE = re.compile(r"自\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*起(?:施行|生效|执行)")

#: 机构别名字典（docs/04 §7）
AUTHORITY_KEYWORDS = [
    "国家金融监督管理总局", "中国银行保险监督管理委员会", "银保监会", "中国人民银行",
    "中国证券监督管理委员会", "证监会", "证券交易所", "证券业协会", "保险行业协会",
    "银行保险监督管理", "监督管理",
]


def extract_meta(text: str) -> dict:
    """从全文抽取 title/doc_no/issuing_authority/publish_date/effective_date。"""
    head = text[:1000] if text else ""
    meta: dict = {
        "title": None,
        "doc_no": None,
        "issuing_authority": None,
        "publish_date": None,
        "effective_date": None,
    }

    m = DOC_NO_RE.search(text or "")
    if m:
        meta["doc_no"] = re.sub(r"\s+", "", m.group(0))

    meta["issuing_authority"] = _detect_authority(meta["doc_no"] or "", head)

    dates = DATE_RE.findall(head)
    if dates:
        meta["publish_date"] = _normalize_date(dates[-1])  # 取最后一个（通常是落款）
    m_eff = EFFECTIVE_RE.search(text or "")
    if m_eff:
        meta["effective_date"] = _normalize_date(m_eff.group(1))

    lines = first_non_empty_lines(text or "", 10)
    for line in lines:
        if 6 <= len(line) <= 60 and not DOC_NO_RE.search(line):
            meta["title"] = line.strip()
            break
    return meta


def _detect_authority(doc_no: str, head: str) -> Optional[str]:
    for name in AUTHORITY_KEYWORDS:
        if doc_no and name in doc_no:
            return name
    # 未命中则取首页前 5 行中包含关键词的最短行
    candidates = []
    for line in first_non_empty_lines(head, 5):
        if any(k in line for k in ("银行", "证券", "保险", "监督管理")):
            candidates.append(line.strip())
    return min(candidates, key=len) if candidates else None


def _normalize_date(raw: str) -> str:
    m = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", raw.strip())
    if not m:
        return raw
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
