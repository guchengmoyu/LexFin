"""知识点接口（docs/06 §5.6）。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.constants import Role
from app.core.deps import get_current_user, get_db, require_role
from app.core.response import success
from app.models.user import User
from app.schemas.knowledge_point import (
    KnowledgePointCreate,
    KnowledgePointUpdate,
    SourceBindRequest,
    VerifyRequest,
)
from app.services.knowledge_point import knowledge_point_service as kps

router = APIRouter(prefix="/knowledge-points", tags=["05 Knowledge Points"])


@router.get("")
def list_kp(
    kb_id: Optional[int] = None,
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    timeliness: Optional[str] = None,
    verify_status: Optional[str] = None,
    status: Optional[str] = None,
    difficulty: Optional[int] = None,
    keyword: Optional[str] = None,
    has_source: Optional[bool] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    sort: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    filters = {
        "kb_id": kb_id, "category": category, "sub_category": sub_category,
        "timeliness": timeliness, "verify_status": verify_status, "status": status,
        "difficulty": difficulty, "keyword": keyword, "has_source": has_source,
    }
    return success(kps.list(db, filters, page, size))


@router.post("")
def create_kp(
    payload: KnowledgePointCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(kps.create(db, payload.model_dump(), user))


@router.get("/stats")
def kp_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """知识点统计（验收用，docs/06 §5.6）。"""
    return success(kps.stats(db))


@router.get("/export")
def export_kp(
    kb_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    import csv
    import io

    rows = kps.export(db, kb_id)
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=knowledge_points.csv"},
    )


@router.post("/import")
async def import_kp(
    file: UploadFile = File(...),
    kb_id: int = Form(...),
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    """批量导入（Excel/CSV），是达成 1000 条知识点指标的主要通道。"""
    data = await file.read()
    return success(kps.import_file(db, user, kb_id, file.filename or "import", data, dry_run))


@router.post("/{kp_id}/verify")
def verify_kp(
    kp_id: int,
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(kps.verify(db, kp_id, user, payload.model_dump()))


@router.get("/{kp_id}")
def kp_detail(kp_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return success(kps.detail(db, kp_id))


@router.put("/{kp_id}")
def update_kp(
    kp_id: int,
    payload: KnowledgePointUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(kps.update(db, kp_id, payload.model_dump()))


@router.delete("/{kp_id}")
def delete_kp(
    kp_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(kps.delete(db, kp_id))


@router.get("/{kp_id}/sources")
def kp_sources(
    kp_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return success(kps.sources(db, kp_id))


@router.post("/{kp_id}/sources")
def bind_source(
    kp_id: int,
    payload: SourceBindRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(kps.bind_source(db, kp_id, payload.model_dump()))


@router.delete("/{kp_id}/sources/{source_id}")
def unbind_source(
    kp_id: int,
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(kps.unbind_source(db, kp_id, source_id))


@router.get("/{kp_id}/related")
def kp_related(
    kp_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """条文关联查询 FR-32（docs/05 §11）：context / same_topic / supersede。"""
    return success(kps.related(db, kp_id))
