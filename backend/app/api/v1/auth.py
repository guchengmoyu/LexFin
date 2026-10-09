"""认证接口（docs/06 §5.1）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth import auth_service

router = APIRouter(prefix="/auth", tags=["01 Auth"])


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    data = auth_service.register(
        db,
        username=payload.username,
        password=payload.password,
        real_name=payload.real_name,
        email=payload.email,
        invite_code=payload.invite_code,
    )
    return success(data)


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    return success(auth_service.login(db, payload.username, payload.password))


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return success(auth_service.me(user))


@router.post("/logout")
def logout():
    """无状态实现，前端负责清除本地 token（docs/06 §5.1）。"""
    return success(None)
