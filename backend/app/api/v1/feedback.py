"""反馈与人工校验接口（docs/06 §5.11）。/qa/reviews/stats 是 85% 准确率验收入口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.constants import Role
from app.core.deps import get_current_user, get_db, require_role
from app.core.response import success
from app.models.user import User
from app.schemas.misc import FeedbackCreate, ReviewCreate
from app.services.favorite import feedback_service, review_service

router = APIRouter(tags=["10 Feedback & Review"])


@router.post("/qa/messages/{message_id}/feedback")
def submit_feedback(
    message_id: int,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(feedback_service.submit(db, user, message_id, payload.model_dump()))


@router.get("/qa/feedback")
def list_feedback(
    status: Optional[str] = None,
    rating: Optional[int] = None,
    reason: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    filters = {"status": status, "rating": rating, "reason": reason}
    return success(feedback_service.list(db, filters, page, size))


@router.post("/qa/reviews")
def submit_review(
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    """人工校验提交（★ 85% 准确率的落库入口）。"""
    return success(review_service.submit(db, user, payload.model_dump()))


@router.get("/qa/reviews/stats")
def review_stats(
    batch_no: str = Query(..., description="评测批次号，如 EVAL-20250601"),
    target_type: str = Query("answer"),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    """准确率统计：pass 字段直接对照 ≥0.85 阈值（答辩现场最有说服力的一屏）。"""
    return success(review_service.stats(db, batch_no, target_type))
