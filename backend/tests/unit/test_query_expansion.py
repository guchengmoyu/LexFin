"""检索式扩展单元测试（docs/05 §2.4）。

覆盖：LLM 输出解析（纯 JSON / 夹带解释 / 无方括号）、清洗去重、
开关与长度门槛、成功路径与失败降级（超时、抛错、空输出）。
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.rag import query_expansion
from app.rag.query_expansion import (
    _clean_queries,
    _parse_array,
    expand_queries,
    should_expand,
)


@pytest.fixture(autouse=True)
def _clear_expansion_cache():
    """扩展结果有进程内缓存，测试间必须隔离。"""
    query_expansion._CACHE.clear()
    yield
    query_expansion._CACHE.clear()


class _JsonLLM:
    """返回固定文本的假 LLM；可指定异常模拟线上失败。"""

    def __init__(self, text: str = "", exc: Exception | None = None) -> None:
        self.text = text
        self.exc = exc
        self.calls = 0

    async def ainvoke(self, prompt, **kwargs):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.text


@pytest.mark.unit
def test_parse_plain_json_array():
    text = '["未经批准擅自设立证券公司的处罚", "无证经营证券业务的取缔"]'
    assert _parse_array(text) == [
        "未经批准擅自设立证券公司的处罚",
        "无证经营证券业务的取缔",
    ]


@pytest.mark.unit
def test_parse_json_with_chatter_around():
    text = '好的，改写结果如下：["适用本法规定", "予以取缔"] 希望有帮助。'
    assert _parse_array(text) == ["适用本法规定", "予以取缔"]


@pytest.mark.unit
def test_parse_without_brackets_falls_back_to_quotes():
    text = '1. "有价证券的范围" 2. "国务院依法认定"'
    assert _parse_array(text) == ["有价证券的范围", "国务院依法认定"]


@pytest.mark.unit
def test_parse_empty_text():
    assert _parse_array("") == []
    assert _parse_array("模型什么也没说") == []


@pytest.mark.unit
def test_clean_queries_dedup_and_limit():
    raw = ["1. 证券的定义", "证券的定义", "证券的定义是什么？", "", "x", "未经批准擅自经营证券业务"]
    out = _clean_queries(raw, "证券的定义是什么？", limit=2)
    assert out == ["证券的定义", "未经批准擅自经营证券业务"]


@pytest.mark.unit
def test_should_expand_respects_switch(monkeypatch: pytest.MonkeyPatch):
    assert should_expand("证券的定义是什么？") is True
    monkeypatch.setattr(settings, "query_expansion_enabled", False)
    assert should_expand("证券的定义是什么？") is False


@pytest.mark.unit
def test_should_expand_skips_long_question(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "query_expansion_enabled", True)
    monkeypatch.setattr(settings, "query_expansion_max_chars", 20)
    assert should_expand("短问题") is True
    assert should_expand("这个问题非常长" * 10) is False
    assert should_expand("") is False


@pytest.mark.unit
def test_expand_queries_success_and_cache():
    llm = _JsonLLM('["未经批准擅自经营证券业务", "予以取缔"]')
    first = asyncio.run(expand_queries("没有牌照能卖股票吗", llm))
    assert first == ["未经批准擅自经营证券业务", "予以取缔"]
    assert llm.calls == 1
    second = asyncio.run(expand_queries("没有牌照能卖股票吗", llm))
    assert second == first
    assert llm.calls == 1, "同一问题应命中进程内缓存，不再调用 LLM"


@pytest.mark.unit
def test_expand_queries_degrades_on_error():
    llm = _JsonLLM(exc=RuntimeError("boom"))
    assert asyncio.run(expand_queries("没有牌照能卖股票吗", llm)) == []


@pytest.mark.unit
def test_expand_queries_degrades_on_empty_output():
    llm = _JsonLLM("[]")
    assert asyncio.run(expand_queries("没有牌照能卖股票吗", llm)) == []


@pytest.mark.unit
def test_expand_queries_without_llm():
    assert asyncio.run(expand_queries("没有牌照能卖股票吗", None)) == []
