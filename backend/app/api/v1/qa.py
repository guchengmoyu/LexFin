"""问答接口（docs/06 §5.8/§5.9）：非流式 /qa/ask + SSE 流式 /qa/ask/stream。

SSE 事件序列：meta（检索完成立即下发）→ token* → ping(15s) → done / error。
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, limit_qa
from app.core.response import success
from app.models.user import User
from app.schemas.qa import QaAskRequest
from app.services.qa import qa_service

router = APIRouter(tags=["07 QA / 08 Sessions"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 关键：关闭 Nginx 缓冲，否则 SSE 被攒批
}


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/qa/ask")
async def ask(
    payload: QaAskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _limit: None = Depends(limit_qa),
):
    data = await qa_service.ask(db, user, payload.model_dump())
    return success(data)


@router.post("/qa/ask/stream")
async def ask_stream(
    payload: QaAskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _limit: None = Depends(limit_qa),
):
    """SSE 流式问答（前端默认）。客户端断开时服务端仍把已生成内容落库（docs/06 §5.8 规则 4）。"""

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        producer = qa_service.ask_stream(db, user, payload.model_dump())
        ping_task = None

        async def produce() -> None:
            try:
                async for event in producer:
                    await queue.put(event)
            except Exception as exc:  # noqa: BLE001
                await queue.put(("error", {"code": 50030, "message": f"生成失败：{exc}"}))
            finally:
                await queue.put(None)  # 结束哨兵

        task = asyncio.create_task(produce())
        import time

        last_emit = time.monotonic()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield _sse_format("ping", {"ts": int(time.time())})  # 防代理层断连
                    continue
                if event is None:
                    break
                name, data = event
                yield _sse_format(name, data)
                last_emit = time.monotonic()
        finally:
            # 客户端断开：取消生成，但流内部 _finalize 已保证落库
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )


# --------------------------------------------------------------------------- #
#  会话与历史（docs/06 §5.9）
# --------------------------------------------------------------------------- #
@router.get("/qa/sessions")
def list_sessions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(qa_service.list_sessions(db, user, page, size))


@router.get("/qa/sessions/{session_no}")
def session_detail(
    session_no: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(qa_service.session_detail(db, user, session_no))


@router.delete("/qa/sessions/{session_no}")
def delete_session(
    session_no: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(qa_service.delete_session(db, user, session_no))


@router.get("/qa/messages/{message_id}")
def message_detail(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(qa_service.message_detail(db, user, message_id))
