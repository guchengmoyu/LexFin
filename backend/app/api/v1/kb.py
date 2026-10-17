"""知识库接口（docs/06 §5.3）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.constants import Role
from app.core.deps import get_current_user, get_db, require_role
from app.core.response import success
from app.models.user import User
from app.schemas.kb import KbCreateRequest, KbUpdateRequest
from app.services.kb import kb_service

router = APIRouter(prefix="/kb", tags=["02 Knowledge Base"])


@router.get("")
def list_kb(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return success(kb_service.list(db))


@router.post("")
def create_kb(
    payload: KbCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
):
    return success(kb_service.create(db, payload.model_dump(), user))


@router.get("/{kb_id}")
def kb_detail(kb_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return success(kb_service.get(db, kb_id))


@router.put("/{kb_id}")
def update_kb(
    kb_id: int,
    payload: KbUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
):
    return success(kb_service.update(db, kb_id, payload.model_dump()))


@router.delete("/{kb_id}")
def delete_kb(
    kb_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.admin)),
):
    return success(kb_service.delete(db, kb_id))


@router.get("/{kb_id}/stats")
def kb_stats(kb_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return success(kb_service.stats(db, kb_id))
