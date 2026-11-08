"""安全：bcrypt 密码哈希（cost=12）与 JWT 签发/校验（HS256，docs/06 §6）。

响应与日志中永不出现 password_hash。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import bcrypt
import jwt

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.exceptions import BizError


# --------------------------------------------------------------------------- #
#  密码
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    rounds = max(4, min(16, settings.password_bcrypt_rounds))
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
#  JWT
# --------------------------------------------------------------------------- #
def create_access_token(
    user_id: int,
    username: str,
    role: str,
    expires_minutes: Optional[int] = None,
) -> tuple[str, int]:
    """返回 (token, expires_in 秒)。载荷仅含 sub/username/role/exp/iat（docs/06 §6）。"""
    now = datetime.utcnow()
    expire_delta = timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + expire_delta,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, int(expire_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT；失败抛 40101/40102。"""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise BizError(ErrorCode.TOKEN_EXPIRED, "凭证已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise BizError(ErrorCode.TOKEN_INVALID, "凭证无效，请重新登录") from exc


# --------------------------------------------------------------------------- #
#  注册校验（docs/06 §5.1）
# --------------------------------------------------------------------------- #
def validate_username(username: str) -> None:
    import re

    if not re.fullmatch(r"[A-Za-z0-9_]{4,50}", username or ""):
        raise BizError(ErrorCode.PARAM_INVALID, "用户名需为 4~50 位字母、数字或下划线")


def validate_password(password: str) -> None:
    import re

    if not password or not (8 <= len(password) <= 32):
        raise BizError(ErrorCode.PARAM_INVALID, "密码长度需为 8~32 位")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise BizError(ErrorCode.PARAM_INVALID, "密码需同时包含字母与数字")
