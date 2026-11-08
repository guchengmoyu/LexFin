"""API 路由汇总（/api/v1）。"""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    documents,
    favorites,
    feedback,
    health,
    kb,
    knowledge_points,
    qa,
    retrieve,
    stats,
    tasks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(kb.router)
api_router.include_router(documents.router)
api_router.include_router(tasks.router)
api_router.include_router(knowledge_points.router)
api_router.include_router(retrieve.router)
api_router.include_router(qa.router)
api_router.include_router(favorites.router)
api_router.include_router(feedback.router)
api_router.include_router(stats.router)
