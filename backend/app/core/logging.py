"""日志：loguru 配置 + request_id ContextVar（docs/02 §7.3）。

问答链路必须打印结构化耗时：rewrite/retrieve/rerank/llm_ttft/total。
"""
from __future__ import annotations

import contextvars
import sys
from typing import Optional

from loguru import logger

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)

_configured = False


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """初始化 loguru：控制台输出 + 可选文件轮转，并自动注入 request_id。"""
    global _configured
    if _configured:
        return
    logger.remove()
    logger.configure(
        extra={"request_id": "-"},
        patcher=_patch_request_id,
    )
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "rid={extra[request_id]} | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, format=fmt, level=level, enqueue=True)
    if log_file:
        logger.add(log_file, format=fmt, level=level, rotation="20 MB", retention="14 days")
    _configured = True


def _patch_request_id(record: dict) -> None:  # pragma: no cover - loguru 回调
    record["extra"]["request_id"] = request_id_var.get() or "-"


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str:
    return request_id_var.get() or "-"
