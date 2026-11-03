"""BM25 关键词通道（Milvus 2.5）单测：不依赖真实 Milvus，直接替换 search。"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.rag.query_rewriter import QueryInfo
from app.rag.retriever import bm25_retriever


def _row(**overrides):
    row = {
        "pk": "kp_1",
        "source_type": "knowledge_point",
        "source_id": 1,
        "kb_id": 2,
        "document_id": 9,
        "category": "证券",
        "timeliness": "effective",
        "article_no": "第二条",
        "page_no": 3,
        "chunk_index": -1,
        "publish_year": 2019,
        "doc_title": "中华人民共和国证券法",
        "doc_no": "主席令第三十七号",
        "issuing_authority": "全国人民代表大会常务委员会",
        "content": "在中华人民共和国境内，股票、公司债券……适用本法。",
        "_score": 12.5,
    }
    row.update(overrides)
    return row


@pytest.fixture()
def bm25_on(monkeypatch):
    monkeypatch.setattr(settings, "keyword_backend", "bm25")
    yield
    monkeypatch.setattr(settings, "keyword_backend", "mysql")


def test_backend_off_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "keyword_backend", "mysql")
    assert bm25_retriever.search_bm25(QueryInfo("证券", "证券")) == []


def test_search_maps_rows_to_items(bm25_on, monkeypatch):
    monkeypatch.setattr(
        bm25_retriever.milvus_bm25, "search", lambda *a, **k: [_row(), _row(pk="chunk_7", source_type="chunk", source_id=7, chunk_index=4)]
    )
    items = bm25_retriever.search_bm25(QueryInfo("证券的定义", "证券的定义"))

    assert [i.source_type for i in items] == ["knowledge_point", "chunk"]
    assert [i.keyword_rank for i in items] == [1, 2]
    assert items[0].doc_title == "中华人民共和国证券法"
    assert items[0].content.startswith("在中华人民共和国境内")
    assert items[0].score == pytest.approx(12.5)
    assert items[1].chunk_index == 4


def test_article_clue_is_ranked_first(bm25_on, monkeypatch):
    captured = {}

    def _fake_query(expr, limit=20, output_fields=None):
        captured["expr"] = expr
        return [_row(source_id=3, article_no="第二条")]

    monkeypatch.setattr(bm25_retriever.milvus_bm25, "query", _fake_query)
    monkeypatch.setattr(
        bm25_retriever.milvus_bm25,
        "search",
        lambda *a, **k: [
            _row(source_id=2, article_no="第三条"),
            _row(source_id=3, article_no="第二条"),  # 与线索命中重复，应去重
        ],
    )
    info = QueryInfo("证券法第二条", "证券法第二条", article_nos=["第二条"])
    items = bm25_retriever.search_bm25(info)

    assert "article_no in [\"第二条\"]" in captured["expr"]
    assert [i.source_id for i in items] == [3, 2]
    assert [i.keyword_rank for i in items] == [1, 2]


def test_kb_filter_expression(bm25_on, monkeypatch):
    captured = {}

    def _fake(text, limit, expr=None, output_fields=None):
        captured.update(text=text, limit=limit, expr=expr)
        return []

    monkeypatch.setattr(bm25_retriever.milvus_bm25, "search", _fake)
    bm25_retriever.search_bm25(QueryInfo("资本充足率", "资本充足率"), kb_ids=[1, 3], top_k=7)

    assert captured["text"] == "资本充足率"
    assert captured["limit"] == 7
    assert captured["expr"] == "kb_id in [1,3]"


def test_search_failure_degrades_to_empty(bm25_on, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("milvus down")

    monkeypatch.setattr(bm25_retriever.milvus_bm25, "search", _boom)
    assert bm25_retriever.search_bm25(QueryInfo("证券", "证券")) == []
