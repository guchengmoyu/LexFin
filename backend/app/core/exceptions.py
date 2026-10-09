"""业务异常与全局异常处理（docs/02 §7.2）。

业务异常统一抛 BizError(code, message)，由全局处理器渲染为统一响应体；
未捕获异常统一 500 + code=50000，堆栈只进日志，不返回给前端。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.constants import ERROR_HTTP_STATUS, ErrorCode


class BizError(Exception):
    """业务异常：code 取自 docs/06 §3 错误码表，message 为面向用户的中文。"""

    def __init__(
        self,
        code: int,
        message: str,
        data: Any = None,
        http_status: Optional[int] = None,
        headers: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status or ERROR_HTTP_STATUS.get(code, 400)
        self.headers = headers or {}

    def to_response(self, request_id: str) -> JSONResponse:
        from app.core.response import fail

        return fail(
            code=self.code,
            message=self.message,
            data=self.data,
            request_id=request_id,
            http_status=self.http_status,
            headers=self.headers,
        )


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def register_exception_handlers(app: FastAPI) -> None:
    """把统一异常渲染挂到 FastAPI 实例。"""

    @app.exception_handler(BizError)
    async def _biz_error(request: Request, exc: BizError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.error("业务异常 code={} message={}", exc.code, exc.message)
        else:
            logger.warning("业务异常 code={} message={}", exc.code, exc.message)
        return exc.to_response(get_request_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        from app.core.response import fail

        # 只取第一个字段错误，避免向用户暴露 Pydantic 细节
        detail = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in detail.get("loc", []) if x != "body") or "-"
        message = f"参数校验失败：{field}"
        logger.warning("参数校验失败 {}", exc.errors())
        return fail(
            code=ErrorCode.PARAM_INVALID,
            message=message,
            data={"field": field},
            request_id=get_request_id(request),
            http_status=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        from app.core.response import fail

        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.NOT_FOUND,
            429: ErrorCode.TOO_MANY_REQUESTS,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.PARAM_INVALID)
        message = exc.detail if isinstance(exc.detail, str) else "请求无法处理"
        return fail(
            code=code,
            message=message,
            request_id=get_request_id(request),
            http_status=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unknown_error(request: Request, exc: Exception) -> JSONResponse:
        from app.core.response import fail

        logger.exception("未捕获异常: {}", exc)
        return fail(
            code=ErrorCode.INTERNAL_ERROR,
            message="服务异常，请稍后重试",
            request_id=get_request_id(request),
            http_status=500,
        )
