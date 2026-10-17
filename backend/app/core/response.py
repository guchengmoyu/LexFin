"""统一响应结构（docs/06 §2）。

成功：{"code": 0, "message": "success", "data": ..., "request_id": "..."}
失败：{"code": 40xxx, "message": "中文可读信息", "data": null, "request_id": "..."}
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from fastapi.responses import JSONResponse

from app.core.constants import ErrorCode


def build_payload(code: int, message: str, data: Any, request_id: str) -> dict:
    return {"code": code, "message": message, "data": data, "request_id": request_id}


def success(data: Any = None, message: str = "success", request_id: str = "") -> dict:
    if not request_id:
        from app.core.logging import get_request_id

        request_id = get_request_id()
    return build_payload(ErrorCode.OK, message, data, request_id)


def fail(
    code: int,
    message: str,
    data: Any = None,
    request_id: str = "",
    http_status: int = 400,
    headers: Optional[dict] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content=build_payload(code, message, data, request_id),
        headers=headers,
    )


def paged(total: int, page: int, size: int, items: Sequence[Any]) -> dict:
    """统一分页结构：{total, page, size, pages, items}。"""
    return {
        "total": int(total),
        "page": int(page),
        "size": int(size),
        "pages": max(1, math.ceil(total / size)) if total else 0,
        "items": list(items),
    }
