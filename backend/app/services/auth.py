"""认证服务（docs/06 §5.1）：注册 / 登录 / 当前用户。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import ErrorCode, Role
from app.core.exceptions import BizError
from app.core.security import (
    create_access_token,
    hash_password,
    validate_password,
    validate_username,
    verify_password,
)
from app.models.user import User
from app.utils.time import now


class AuthService:
    def register(
        self,
        db: Session,
        username: str,
        password: str,
        real_name: Optional[str] = None,
        email: Optional[str] = None,
        invite_code: Optional[str] = None,
    ) -> dict:
        validate_username(username)
        validate_password(password)
        exists = db.scalar(select(User).where(User.username == username))
        if exists:
            raise BizError(ErrorCode.CONFLICT, "用户名已存在")
        role = Role.viewer.value
        if invite_code and invite_code == settings.editor_invite_code:
            role = Role.editor.value  # 邀请码匹配授予 editor（docs/06 §5.1）
        user = User(
            username=username,
            password_hash=hash_password(password),
            real_name=real_name,
            email=email,
            role=role,
            status=1,
            created_at=now(),
            updated_at=now(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def login(self, db: Session, username: str, password: str) -> dict:
        user = db.scalar(select(User).where(User.username == username))
        if user is None or not verify_password(password, user.password_hash):
            raise BizError(ErrorCode.LOGIN_FAILED, "用户名或密码错误")
        if user.status != 1:
            raise BizError(ErrorCode.USER_DISABLED, "账号已被禁用，请联系管理员")
        user.last_login_at = now()
        db.commit()
        token, expires_in = create_access_token(user.id, user.username, user.role)
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": {
                "id": user.id,
                "username": user.username,
                "real_name": user.real_name,
                "role": user.role,
            },
        }

    def me(self, user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role,
            "email": user.email,
            "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M:%S")
            if user.last_login_at
            else None,
        }


auth_service = AuthService()
