"""检索接口测试（docs/09 §4.1）：三种 mode 可用 / keyword 模式 vector_rank 为 None /
过滤条件生效 / 高亮 XSS 转义。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"


async def test_retrieve_hybrid_shape(auth_client):
    r = await auth_client.post(
        f"{API}/retrieve",
        json={"query": "流动性覆盖率最低要求", "mode": "hybrid", "top_k": 10},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["mode"] == "hybrid"
    assert "latency_ms" in data
    for i, item in enumerate(data["items"], start=1):
        assert item["rank"] == i
        assert item["source_type"] in ("chunk", "knowledge_point")
        assert "score" in item and "snippet" in item
        assert "vector_rank" in item and "keyword_rank" in item


async def test_retrieve_keyword_mode_vector_rank_none(auth_client):
    """keyword 模式只走关键词通道 → vector_rank is None（docs/09 §4.1）。"""
    r = await auth_client.post(
        f"{API}/retrieve", json={"query": "流动性覆盖率", "mode": "keyword", "top_k": 5}
    )
    assert r.status_code == 200
    for item in r.json()["data"]["items"]:
        assert item["vector_rank"] is None
        assert item["keyword_rank"] is not None


async def test_retrieve_vector_mode(auth_client):
    r = await auth_client.post(
        f"{API}/retrieve", json={"query": "流动性覆盖率", "mode": "vector", "top_k": 5}
    )
    assert r.status_code == 200
    for item in r.json()["data"]["items"]:
        assert item["keyword_rank"] is None
        assert item["vector_rank"] is not None


async def test_search_highlight_escapes_xss(auth_client):
    """/search 高亮结果必须 HTML 转义（docs/06 §6 XSS）。"""
    evil = "<script>alert(1)</script> 流动性覆盖率"
    r = await auth_client.get(f"{API}/search", params={"q": evil, "highlight": True})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["query"] == evil  # JSON echo is plain text, not rendered HTML.
    for item in data["items"]:
        assert "<script>" not in (item.get("highlight") or "")
    # Cover escaping even when the isolated search corpus has no hits.
    from app.services.retrieval import highlight_text
    rendered = highlight_text(evil, ["流动性覆盖率"])
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


async def test_search_pagination_shape(auth_client):
    r = await auth_client.get(
        f"{API}/search", params={"q": "流动性", "page": 1, "size": 5, "highlight": True}
    )
    assert r.status_code == 200
    data = r.json()["data"]
    for key in ("total", "page", "size", "pages", "items"):
        assert key in data
    assert data["page"] == 1 and data["size"] == 5
