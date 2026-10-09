"""入库任务接口（docs/06 §5.5）。前端按 1.5 秒轮询任务进度。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import ErrorCode, Role
from app.core.deps import get_current_user, get_db, require_role
from app.core.exceptions import BizError
from app.core.response import paged, success
from app.models.task import IngestTask
from app.models.user import User

router = APIRouter(prefix="/tasks", tags=["04 Tasks"])


def _task_dict(task: IngestTask) -> dict:
    return {
        "task_no": task.task_no,
        "document_id": task.document_id,
        "kb_id": task.kb_id,
        "task_type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "stage_message": task.stage_message,
        "total_chunks": task.total_chunks,
        "done_chunks": task.done_chunks,
        "error_message": task.error_message,
        "duration_ms": task.duration_ms,
        "started_at": task.started_at.strftime("%Y-%m-%d %H:%M:%S") if task.started_at else None,
        "finished_at": task.finished_at.strftime("%Y-%m-%d %H:%M:%S") if task.finished_at else None,
    }


@router.get("")
def list_tasks(
    status: Optional[str] = None,
    kb_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    query = select(IngestTask)
    if status:
        query = query.where(IngestTask.status == status)
    if kb_id:
        query = query.where(IngestTask.kb_id == kb_id)
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(IngestTask.created_at.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return success(paged(total, page, size, [_task_dict(t) for t in rows]))


@router.get("/{task_no}")
def task_detail(
    task_no: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    task = db.scalar(select(IngestTask).where(IngestTask.task_no == task_no))
    if task is None:
        raise BizError(ErrorCode.NOT_FOUND, "任务不存在")
    return success(_task_dict(task))
