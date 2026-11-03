"""口语化提问的检索式扩展（docs/05 §2.4）。

问题背景：制度库用的是法规原文表述，用户却常问口语问题
（「证券的定义是什么？」「没有营业执照还能继续营业吗」）。
这类问题的关键词往往是「定义 / 还能 / 没有 / 获得」等泛词，
在 MySQL ngram 的 NATURAL LANGUAGE MODE（OR 语义）下 IDF 很高，
会把领域词压下去，导致召回的全是与问题无关的条文。

方案：一次低成本的 LLM 调用，把问题改写成 2~3 条「制度原文式」检索式，
与原问题一起做多路召回 + 加权 RRF（见 hybrid_retriever.retrieve_multi）。
成本控制：只对短问题触发；超时 / 失败 / 解析失败一律返回 []，
链路退化为单查询，保证可用性不受影响。
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from typing import List, Optional

from loguru import logger

from app.core.config import settings

EXPANSION_PROMPT = """你是金融监管制度检索助手。把用户的口语化提问改写成 2~3 条
用于检索监管制度原文的查询语句。

要求：
1. 使用监管制度原文的法律/监管表述（例如「未经批准擅自设立」「予以取缔」
   「适用本法」「有价证券」「国务院依法认定」）；
2. 保留提问中的主体、行为、数字与处罚措施，去掉「如果 / 吗 / 还能 / 定义 / 意思」
   这类口语词与泛化词；
3. 每条 6~30 字，不要编号，不要解释，不要输出除数组外的任何文字；
4. 只输出 JSON 字符串数组，例如 ["...", "..."]。

【问题】{question}"""

#: 进程内缓存（同一问题重复提问很常见，扩展结果稳定）
_CACHE: "OrderedDict[str, List[str]]" = OrderedDict()
_CACHE_MAX = 256

_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_QUOTED_RE = re.compile(r"[\"“]([^\"”]{2,60})[\"”]")


def _parse_array(text: str) -> List[str]:
    """解析 LLM 输出：优先 JSON 数组，其次从文本里抠引号片段。"""
    if not text:
        return []
    m = _ARRAY_RE.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return [str(x) for x in data if isinstance(x, (str, int, float))]
        except (ValueError, TypeError):
            pass
    # 兜底：模型偶尔漏掉方括号或带解释文字
    return [q for q in _QUOTED_RE.findall(text) if q]


def _clean_queries(raw: List[str], question: str, limit: int) -> List[str]:
    """去噪：去首尾标点/编号、去与问题重复者、限长去重。"""
    out: List[str] = []
    seen = {question.strip()}
    for item in raw:
        q = re.sub(r"^\s*\d+[.、)]\s*", "", str(item)).strip(" \t\"'“”‘’。，,；;")
        if not 2 <= len(q) <= 60:
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= limit:
            break
    return out


def should_expand(question: str) -> bool:
    """触发条件：开关打开且是「短问题」（长问题通常已自带专业表述）。"""
    if not settings.query_expansion_enabled:
        return False
    q = (question or "").strip()
    return 2 <= len(q) <= settings.query_expansion_max_chars


async def expand_queries(question: str, llm=None) -> List[str]:
    """把口语问题扩展为制度原文式检索式；失败返回 []（降级，不抛异常）。"""
    q = (question or "").strip()
    if not q or not should_expand(q):
        return []
    if llm is None:
        return []
    cached = _CACHE.get(q)
    if cached is not None:
        _CACHE.move_to_end(q)
        return list(cached)

    prompt = EXPANSION_PROMPT.format(question=q)
    timeout = settings.query_expansion_timeout_ms / 1000.0
    limit = max(1, settings.query_expansion_max_queries)

    async def _call() -> str:
        return await llm.ainvoke(prompt, temperature=0.0, max_tokens=160)

    try:
        text = await asyncio.wait_for(_call(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.info("检索式扩展超时（{}ms），退化为单查询: {}", settings.query_expansion_timeout_ms, q)
        return []
    except Exception as exc:  # pragma: no cover - 依赖外部 LLM
        logger.debug("检索式扩展失败，退化为单查询: {}", exc)
        return []

    queries = _clean_queries(_parse_array(text or ""), q, limit)
    if not queries:
        logger.debug("检索式扩展解析为空: {}", (text or "")[:80])
        return []
    _CACHE[q] = list(queries)
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    logger.info("检索式扩展 {} → {}", q, queries)
    return queries
