"""健康检查与系统接口（docs/06 §5.2）。

/health 不鉴权，供 Docker healthcheck 与运维使用，HTTP 状态始终 200。
"""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.response import success
from app.models.user import User
from app.services.stats import stats_service

router = APIRouter(tags=["00 Health & Config"])

_START_TIME = datetime.now()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    dependencies: dict = {}
    status = "ok"

    # MySQL
    try:
        from app.db.session import ping

        latency = ping()
        dependencies["mysql"] = {"status": "ok", "latency_ms": round(latency, 1)}
    except Exception as exc:
        dependencies["mysql"] = {"status": "error", "message": str(exc)[:200]}
        status = "degraded"

    # Milvus
    try:
        from app.rag.indexer import indexer

        t0 = time.perf_counter()
        entities = indexer.count()
        dependencies["milvus"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "collection": settings.milvus_alias,
            "entities": entities,
        }
    except Exception as exc:
        dependencies["milvus"] = {"status": "error", "message": str(exc)[:200]}
        status = "degraded"

    # LLM（轻量探测，不实际调用计费接口）
    dependencies["llm"] = {
        "status": "ok" if settings.llm_api_key and not settings.llm_api_key.startswith("sk-CHANGE_ME") else "error",
        "model": settings.llm_model,
        "message": None if settings.llm_api_key and not settings.llm_api_key.startswith("sk-CHANGE_ME") else "未配置 LLM_API_KEY",
    }
    if dependencies["llm"]["status"] == "error":
        status = "degraded"

    # OCR
    try:
        from app.rag.parser.ocr_engine import ocr_engine

        ok, detail = ocr_engine.available()
        dependencies["ocr"] = (
            {"status": "ok", "langs": settings.ocr_lang.split("+")} if ok
            else {"status": "error", "message": detail}
        )
        if not ok:
            status = "degraded"
    except Exception as exc:
        dependencies["ocr"] = {"status": "error", "message": str(exc)[:200]}
        status = "degraded"

    # Embedding
    dependencies["embedding"] = {
        "status": "ok",
        "model": settings.embedding_model,
        "dim": settings.embedding_dim,
    }

    return success(
        {
            "status": status,
            "version": settings.app_version,
            "uptime_seconds": int((datetime.now() - _START_TIME).total_seconds()),
            "dependencies": dependencies,
        }
    )


@router.get("/system/config")
def system_config(user: User = Depends(get_current_user)):
    return success(stats_service.system_config())
