"""统计接口（docs/06 §5.2）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.services.stats import stats_service

router = APIRouter(prefix="/stats", tags=["00 Health & Config"])


@router.get("/overview")
def stats_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return success(stats_service.overview(db))
