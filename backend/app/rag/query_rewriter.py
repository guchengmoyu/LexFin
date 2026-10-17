"""查询理解（docs/05 §2）：清洗 / 结构化线索 / 关键词抽取 / 多轮指代改写。

结构化线索（文号、条号）是关键词检索的强特征：命中结果直接置顶（权重 ×1.5）。
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from loguru import logger

from app.core.config import settings

try:
    import jieba
    import jieba.analyse
except ImportError:  # pragma: no cover
    jieba = None  # type: ignore

# --------------------------------------------------------------------------- #
#  结构化线索正则（docs/05 §2.1）
# --------------------------------------------------------------------------- #
ARTICLE_NO_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")
DOC_NO_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,8}(?:令|公告|通知|发|字)?\s*[〔\[（(]\s*\d{4}\s*[〕\]）)]\s*第?\s*\d+\s*号"
    r"|[\u4e00-\u9fa5]{2,8}(?:令|公告|通知|发|字)\s*\d{4}\s*年?\s*第?\s*\d+\s*号"
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*年?")
NUM_UNIT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|万元|亿元|日|个月|年|倍|人|次)")

# 中文停用词 + 金融领域停用词（docs/05 §2.2）
STOPWORDS = {
    "请问", "如何", "是否", "规定", "要求", "标准", "什么", "哪些", "怎么", "怎样",
    "的", "了", "是", "在", "和", "与", "及", "或", "对", "中", "为", "有", "被",
    "该", "这", "那", "我", "你", "他", "们", "要", "会", "可以", "可以吗", "吗", "呢",
    "啊", "吧", "以及", "并且", "而且", "进行", "相关", "有关", "关于", "根据",
}

# 金融术语词典（命中 ×2.0，docs/05 §2.2）
FINANCE_TERMS = {
    "LCR", "流动性覆盖率", "净资本", "偿付能力充足率", "投资者适当性", "优质流动性资产",
    "流动性风险", "信用风险", "市场风险", "操作风险", "资本充足率", "拨备覆盖率",
    "不良贷款率", "杠杆率", "准备金", "反洗钱", "信息披露", "关联交易", "偿二代",
    "风险评级", "适当性管理", "资管产品", "债券", "融资融券", "做市", "退市",
}


@dataclass
class QueryInfo:
    """查询理解产物，贯穿检索链路。"""

    original: str
    cleaned: str
    keywords: List[str] = field(default_factory=list)
    article_nos: List[str] = field(default_factory=list)
    doc_nos: List[str] = field(default_factory=list)
    rewritten: Optional[str] = None

    @property
    def effective_query(self) -> str:
        """改写成功用改写结果，否则用清洗后的原始问题。"""
        return self.rewritten or self.cleaned

    @property
    def keyword_query(self) -> str:
        """MySQL FULLTEXT 查询串（ngram 下 OR 语义）。"""
        return " ".join(self.keywords) or self.cleaned

    @property
    def has_structured_clue(self) -> bool:
        return bool(self.article_nos or self.doc_nos)


def clean_question(question: str) -> str:
    """基础清洗：NFKC、去首尾空白、长度限制（docs/05 §2.1）。"""
    q = unicodedata.normalize("NFKC", question or "").strip()
    return q


def extract_keywords(question: str, top_k: int = 8) -> List[str]:
    """关键词抽取：jieba 分词 → 去停用词 → 加权重 → 取 Top-8。"""
    if not question:
        return []
    if jieba is not None:
        words = list(jieba.cut_for_search(question))
    else:  # 兜底：按非中文字符与 2-gram 切分
        words = re.findall(r"[A-Za-z0-9%]+|[\u4e00-\u9fa5]{2,}", question)

    scored: dict[str, float] = {}
    for w in words:
        w = w.strip()
        if not w or w in STOPWORDS or len(w) == 1:
            continue
        score = 1.0
        if w in FINANCE_TERMS or w.upper() in FINANCE_TERMS:
            score = 2.0  # 金融术语
        if re.search(r"\d", w) or NUM_UNIT_RE.fullmatch(w):
            score = 2.0  # 数字 + 单位
        if ARTICLE_NO_RE.fullmatch(w) or DOC_NO_RE.fullmatch(w):
            score = 2.0
        scored[w] = max(scored.get(w, 0.0), score)

    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [w for w, _ in ranked[:top_k]]


def extract_clues(question: str) -> tuple[List[str], List[str]]:
    """抽取条号与文号线索。文号正则可能吸入前导汉字（如「依据银保监会令…」），
    用机构词典裁剪，保证与库中文号可精确/包含匹配（docs/05 §2.1 结构化线索）。"""
    article_nos = list(dict.fromkeys(ARTICLE_NO_RE.findall(question or "")))
    doc_nos = list(dict.fromkeys(_trim_doc_no(m) for m in DOC_NO_RE.findall(question or "")))
    return article_nos, doc_nos


def _trim_doc_no(match: str) -> str:
    """裁掉正则贪婪吸入的前导汉字，保留真实文号（自机构名起）。"""
    for kw in sorted(FINANCE_AUTHORITY_HINTS, key=len, reverse=True):
        idx = match.find(kw)
        if idx > 0:
            return match[idx:]
    # 无词典命中（如「证监发〔2018〕12号」）：保留「令/公告/通知/发/字」前最多 4 字机构简称
    m = re.search(r"(令|公告|通知|发|字)", match)
    if m and m.start() > 0:
        return match[max(0, m.start() - 4):]
    return match


#: 用于文号裁剪的机构词典（与 parser/meta.py 保持同源）
FINANCE_AUTHORITY_HINTS = (
    "国家金融监督管理总局", "中国银行保险监督管理委员会", "中国证券监督管理委员会",
    "中国人民银行", "银保监会", "证监会", "证券交易所", "证券业协会", "保险行业协会",
)


def analyze(question: str) -> QueryInfo:
    """查询理解主入口（不含多轮改写，改写单独调用 rewrite）。"""
    cleaned = clean_question(question)
    article_nos, doc_nos = extract_clues(cleaned)
    return QueryInfo(
        original=question,
        cleaned=cleaned,
        keywords=extract_keywords(cleaned),
        article_nos=article_nos,
        doc_nos=doc_nos,
    )


# --------------------------------------------------------------------------- #
#  多轮指代改写（docs/05 §2.3，P1 默认开启）
# --------------------------------------------------------------------------- #
PRONOUNS = ("它", "这个", "该", "上述", "这条", "那", "其", "这些", "那些")

REWRITE_PROMPT = """下面是用户与助手的对话历史，以及用户的最新提问。
若最新提问包含指代或省略，请改写为一个不依赖上下文、可独立用于检索的完整问题；
若已经是完整问题，原样返回。只输出问题本身，不要任何解释。

【历史】
{history}

【最新提问】{question}"""


def need_rewrite(question: str, has_history: bool) -> bool:
    """触发条件：会话内有历史且提问 < 25 字，或包含指代词（docs/05 §2.3）。"""
    if not settings.multi_turn_enabled or not has_history:
        return False
    q = question or ""
    return len(q) < 25 or any(p in q for p in PRONOUNS)


async def rewrite(
    question: str,
    history: Sequence[tuple[str, str]],
    llm=None,
) -> Optional[str]:
    """多轮指代改写。超时（QUERY_REWRITE_TIMEOUT_MS）或失败 → 返回 None 降级放行。"""
    if llm is None:
        return None
    history_text = "\n".join(
        f"用户：{q}\n助手：{(a or '')[:120]}" for q, a in history
    )
    prompt = REWRITE_PROMPT.format(history=history_text, question=question)
    timeout = settings.query_rewrite_timeout_ms / 1000.0

    async def _call() -> str:
        return await llm.ainvoke(prompt, temperature=0.0, max_tokens=100)

    try:
        result = await asyncio.wait_for(_call(), timeout=timeout)
        result = (result or "").strip()
        if not result or len(result) > 500:
            return None
        return result
    except Exception as exc:
        logger.debug("查询改写降级（原始问题检索）: {}", exc)
        return None
