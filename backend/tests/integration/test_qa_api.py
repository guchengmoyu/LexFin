"""问答接口测试（docs/09 §4.1）：正常回答有 citations / 空问题 40020 / 超长 40021 /
知识库外问题 answer_type='refused'。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"


async def test_ask_empty_question(auth_client):
    r = await auth_client.post(f"{API}/qa/ask", json={"question": "   "})
    assert r.status_code == 400
    assert r.json()["code"] == 40020


async def test_ask_too_long(auth_client):
    r = await auth_client.post(f"{API}/qa/ask", json={"question": "问" * 501})
    assert r.status_code == 400
    assert r.json()["code"] == 40021


async def test_ask_normal_has_citations(auth_client):
    r = await auth_client.post(
        f"{API}/qa/ask",
        json={"question": "商业银行流动性覆盖率的最低要求是多少？", "stream": False},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["answer_type"] in ("answered", "refused")
    if data["answer_type"] == "answered":
        assert data["citations"], "正常回答必须带引用"
        for c in data["citations"]:
            assert f"[{c['cite_index']}]" in data["answer"], "答案中可找回角标"
        assert data["confidence_level"] in ("high", "medium", "low")
        assert data["prompt_version"] == "v1.2"
    else:
        assert "未检索到" in data["answer"]


async def test_ask_out_of_scope_refused(auth_client):
    """知识库外问题必须拒答且不编造内容（AC-06，docs/09 §4.1）。"""
    r = await auth_client.post(
        f"{API}/qa/ask",
        json={"question": "请问明天双色球的中奖号码是多少？", "stream": False},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["answer_type"] == "refused"
    assert "未检索到" in data["answer"]
    assert data["citations"] == []


async def test_sessions_roundtrip(auth_client):
    ask = await auth_client.post(
        f"{API}/qa/ask",
        json={"question": "流动性覆盖率的监管要求是什么？", "stream": False},
    )
    session_no = ask.json()["data"]["session_no"]
    detail = await auth_client.get(f"{API}/qa/sessions/{session_no}")
    assert detail.status_code == 200
    messages = detail.json()["data"]["messages"]
    assert messages[0]["role"] == "user"
    assert any(m["role"] == "assistant" for m in messages)
