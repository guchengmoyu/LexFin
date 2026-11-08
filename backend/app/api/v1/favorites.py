"""收藏接口（docs/06 §5.10）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.misc import FavoriteCreate, FavoriteUpdate
from app.services.favorite import favorite_service

router = APIRouter(prefix="/favorites", tags=["09 Favorites"])


@router.get("")
def list_favorites(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(favorite_service.list(db, user, page, size))


@router.post("")
def add_favorite(
    payload: FavoriteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(favorite_service.add(db, user, payload.message_id, payload.note))


@router.put("/{message_id}")
def update_favorite(
    message_id: int,
    payload: FavoriteUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(favorite_service.update_note(db, user, message_id, payload.note))


@router.delete("/{message_id}")
def remove_favorite(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(favorite_service.remove(db, user, message_id))
