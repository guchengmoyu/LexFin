"""文档接口（docs/06 §5.4）。上传走 multipart/form-data。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.constants import Role
from app.core.deps import get_current_user, get_db, limit_upload, require_role
from app.core.response import success
from app.models.user import User
from app.schemas.kb import DocumentUpdateRequest
from app.services.document import document_service
from app.services.ingest import ingest_service
from app.utils.time import parse_date

router = APIRouter(prefix="/documents", tags=["03 Documents"])


@router.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    kb_id: int = Form(...),
    title: Optional[str] = Form(None),
    doc_no: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    issuing_authority: Optional[str] = Form(None),
    publish_date: Optional[str] = Form(None),
    effective_date: Optional[str] = Form(None),
    expiry_date: Optional[str] = Form(None),
    timeliness: Optional[str] = Form(None),
    keywords: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
    _limit: None = Depends(limit_upload),
):
    """多文件上传：元数据字段应用到全部文件（docs/06 §5.4）。"""
    meta = {
        "title": title,
        "doc_no": doc_no,
        "doc_type": doc_type,
        "issuing_authority": issuing_authority,
        "publish_date": parse_date(publish_date),
        "effective_date": parse_date(effective_date),
        "expiry_date": parse_date(expiry_date),
        "timeliness": timeliness,
        "keywords": keywords,
    }
    results = []
    for f in files:
        data = await f.read()
        result = document_service.upload(db, user, f.filename or "unnamed", data, kb_id, meta)
        results.append(result)
        if result.get("success"):
            # ADR-06：BackgroundTasks 异步执行入库，前端轮询 /tasks/{task_no}
            background_tasks.add_task(ingest_service.run, result["task_no"])

    accepted = sum(1 for r in results if r.get("success"))
    return success(
        {"results": results, "accepted": accepted, "rejected": len(results) - accepted}
    )


@router.get("")
def list_documents(
    kb_id: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    timeliness: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    sort: str = Query("created_at"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    filters = {
        "kb_id": kb_id, "category": category, "status": status, "doc_type": doc_type,
        "timeliness": timeliness, "keyword": keyword, "sort": sort,
    }
    return success(document_service.list(db, filters, page, size))


@router.get("/{doc_id}")
def document_detail(
    doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return success(document_service.detail(db, doc_id))


@router.put("/{doc_id}")
def update_document(
    doc_id: int,
    payload: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(document_service.update(db, doc_id, payload.model_dump()))


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    hard: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    return success(document_service.delete(db, doc_id, hard=hard))


@router.post("/{doc_id}/reparse")
def reparse_document(
    background_tasks: BackgroundTasks,
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    task_no = ingest_service.reparse(db, doc_id, user.id)
    background_tasks.add_task(ingest_service.run, task_no)
    return success({"document_id": doc_id, "task_no": task_no, "status": "pending"})


@router.get("/{doc_id}/chunks")
def document_chunks(
    doc_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return success(document_service.chunks(db, doc_id, page, size))


@router.get("/{doc_id}/download")
def download_document(
    doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    path, name = document_service.download_path(db, doc_id)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/extract-meta")
async def extract_meta(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    """解析预览：只做解析与元数据抽取，不落库（docs/06 §5.4）。"""
    data = await file.read()
    return success(document_service.extract_meta_preview(db, file.filename or "unnamed", data))


@router.post("/ocr-preview")
async def ocr_preview(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.editor)),
):
    """图片 OCR 试跑（P2，docs/06 §4）：不落库，返回识别文本与质量评估。"""
    import io

    from app.core.constants import ErrorCode
    from app.core.exceptions import BizError
    from app.rag.parser.ocr_engine import ocr_engine

    ok, detail = ocr_engine.available()
    if not ok:
        raise BizError(ErrorCode.OCR_UNAVAILABLE, f"OCR 引擎不可用：{detail}")
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(await file.read()))
    except Exception as exc:
        raise BizError(ErrorCode.FILE_EMPTY, "无法读取图片文件") from exc

    paragraphs, avg_conf = ocr_engine.ocr_image(image)
    text = "\n".join(paragraphs)
    return success(
        {
            "file_name": file.filename,
            "paragraphs": paragraphs,
            "text": text,
            "avg_confidence": round(avg_conf, 1),
            "warning": ocr_engine.quality_check(text, avg_conf),
        }
    )
