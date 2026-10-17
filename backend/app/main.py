"""FastAPI 应用入口（docs/02 §7）。

中间件链：CORS → request_id → 访问日志 → （限流为依赖）→ 全局异常处理；
启动钩子：seed（管理员/知识库/配置）+ Milvus 集合初始化。
"""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import set_request_id, setup_logging

setup_logging(settings.log_level)

app = FastAPI(
    title="基于 RAG 的金融制度类知识问答系统",
    description="FinRAG 后端 API（契约见 docs/06-后端接口设计.md）",
    version=settings.app_version,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# --------------------------------------------------------------------------- #
#  中间件链
# --------------------------------------------------------------------------- #
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """request_id 生成/透传 + 访问日志（docs/02 §7.3）。"""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    set_request_id(request_id)
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "{} {} -> {} {:.0f}ms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


register_exception_handlers(app)

# --------------------------------------------------------------------------- #
#  路由
# --------------------------------------------------------------------------- #
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }


# --------------------------------------------------------------------------- #
#  启动钩子
# --------------------------------------------------------------------------- #
@app.on_event("startup")
def on_startup() -> None:
    from app.db.init_milvus import init_milvus
    from app.db.seed import seed_all
    from app.db.session import session_scope

    try:
        with session_scope() as db:
            seed_all(db)
        logger.info("种子数据初始化完成")
    except Exception as exc:
        logger.error("种子数据初始化失败（数据库可能未就绪）: {}", exc)

    try:
        init_milvus()
    except Exception as exc:
        logger.error("Milvus 初始化失败: {}", exc)
