"""检索接口（docs/06 §5.7）：POST /retrieve 混合检索 + GET /search 关键词检索。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.qa import RetrieveRequest
from app.services.retrieval import retrieval_service

router = APIRouter(tags=["06 Retrieve"])


@router.post("/retrieve")
async def retrieve(
    payload: RetrieveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(await retrieval_service.retrieve(db, payload.model_dump()))


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=500),
    kb_id: Optional[int] = None,
    category: Optional[str] = None,
    timeliness: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    mode: str = Query("keyword"),
    highlight: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """关键词检索便捷版（无 LLM，P95 ≤ 500ms）；highlight 结果已做 HTML 转义。"""
    return success(
        await retrieval_service.search(
            db, q, kb_id=kb_id, page=page, size=size, mode=mode,
            highlight=highlight, category=category, timeliness=timeliness,
        )
    )
