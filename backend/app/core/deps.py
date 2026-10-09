"""FastAPI 依赖：数据库 Session、当前用户、角色校验、限流（docs/02 §7.4、docs/06 §6）。"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Optional, Tuple

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import ErrorCode, Role
from app.core.exceptions import BizError
from app.core.security import decode_access_token
from app.db.session import get_db  # noqa: F401  (统一从此处导出)
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """解析 JWT → 加载用户；载荷最小集随 token，不额外查库（NFR 时延预算）。"""
    if credentials is None or not credentials.credentials:
        raise BizError(ErrorCode.UNAUTHORIZED, "未登录或缺少凭证")
    payload = decode_access_token(credentials.credentials)
    user = db.scalar(select(User).where(User.id == int(payload.get("sub", 0))))
    if user is None:
        raise BizError(ErrorCode.TOKEN_INVALID, "凭证无效，请重新登录")
    if user.status != 1:
        raise BizError(ErrorCode.USER_DISABLED, "账号已被禁用，请联系管理员")
    # 附着 request.state，便于日志/操作日志记录
    request.state.user_id = user.id
    request.state.username = user.username
    return user


def require_role(*roles: Role) -> Callable[..., User]:
    """路由级角色校验：dependencies=[Depends(require_role(Role.editor))]。"""
    allowed = {r.value for r in roles} or {r.value for r in Role}

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise BizError(ErrorCode.FORBIDDEN, "无操作权限")
        return user

    return _checker


# --------------------------------------------------------------------------- #
#  限流（内存滑动窗口；单后端实例，ADR-06）
# --------------------------------------------------------------------------- #
class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[Tuple[int, str], Deque[float]] = defaultdict(deque)

    def check(self, user_id: int, bucket: str, limit_per_minute: int) -> None:
        key = (user_id, bucket)
        now_ts = time.monotonic()
        q = self._hits[key]
        while q and now_ts - q[0] > 60.0:
            q.popleft()
        if len(q) >= limit_per_minute:
            retry_after = int(60.0 - (now_ts - q[0])) + 1
            raise BizError(
                ErrorCode.TOO_MANY_REQUESTS,
                f"请求过于频繁，请 {retry_after} 秒后重试",
                headers={"Retry-After": str(retry_after)},
            )
        q.append(now_ts)


rate_limiter = RateLimiter()


def limit(bucket: str, limit_getter: Callable[[], int]) -> Callable[..., None]:
    def _checker(request: Request, user: User = Depends(get_current_user)) -> None:
        rate_limiter.check(user.id, bucket, limit_getter())

    return _checker


limit_qa = limit("qa", lambda: settings.rate_limit_qa_per_minute)
limit_upload = limit("upload", lambda: settings.rate_limit_upload_per_minute)
limit_default = limit("default", lambda: settings.rate_limit_default_per_minute)
