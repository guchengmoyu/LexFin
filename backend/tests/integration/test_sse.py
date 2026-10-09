"""SSE 事件序列测试（docs/09 §4.1 ★）：

事件顺序为 meta → token+ → done；meta 先于任何 token；
done 含 confidence 与 used_citations。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration

API = "/api/v1"


async def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name, data = None, {}
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name:
            events.append((name, data))
    return events


async def test_sse_event_order(auth_client):
    async with auth_client.stream(
        "POST",
        f"{API}/qa/ask/stream",
        json={"question": "商业银行流动性覆盖率的最低要求是多少？", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        assert resp.headers.get("x-accel-buffering") == "no"
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk

    events = await _parse_sse(raw)
    names = [e for e, _ in events]

    # 事件顺序：meta 在最前；token 连续；done 在最后（允许夹杂 ping）
    assert names[0] == "meta", f"meta 必须最先下发，实际 {names}"
    assert "done" == names[-1], f"done 必须最后下发，实际 {names}"
    token_positions = [i for i, n in enumerate(names) if n == "token"]
    assert token_positions, "必须有 token 事件"
    assert "error" not in names

    # meta：含 message_id / session_no / citations
    meta = events[0][1]
    assert meta["message_id"] > 0
    assert meta["session_no"].startswith("s_")
    assert isinstance(meta["citations"], list)

    # done：含 confidence 与 used_citations（docs/06 §5.8）
    done = events[-1][1]
    assert done["answer_type"] in ("answered", "refused")
    assert "confidence" in done and 0.0 <= done["confidence"] <= 1.0
    assert done["confidence_level"] in ("high", "medium", "low")
    assert isinstance(done["used_citations"], list)
    assert "latency_ms" in done and "latency_detail" in done

    # 正常回答时 used_citations 与 token 中的角标一致
    answer = "".join(d.get("delta", "") for e, d in events if e == "token")
    if done["answer_type"] == "answered":
        for idx in done["used_citations"]:
            assert f"[{idx}]" in answer


async def test_sse_meta_before_llm_tokens(auth_client):
    """meta 必须先于任何 token（检索完成立即下发，NFR-02 实现基础）。"""
    async with auth_client.stream(
        "POST",
        f"{API}/qa/ask/stream",
        json={"question": "流动性覆盖率的计算公式是什么？", "stream": True},
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk
    names = [e for e, _ in await _parse_sse(raw)]
    first_token = names.index("token") if "token" in names else len(names)
    assert names.index("meta") < first_token


async def test_sse_history_persisted(auth_client):
    """流式问答后可从历史接口完整回看（含引用）。"""
    async with auth_client.stream(
        "POST",
        f"{API}/qa/ask/stream",
        json={"question": "商业银行的流动性覆盖率有什么要求？", "stream": True},
    ) as resp:
        raw = ""
        async for chunk in resp.aiter_text():
            raw += chunk
    events = await _parse_sse(raw)
    meta = events[0][1]
    detail = await auth_client.get(f"{API}/qa/messages/{meta['message_id']}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["role"] == "assistant"
    assert data["content"], "已生成内容必须落库"
    assert data["prompt_version"] == "v1.2"
