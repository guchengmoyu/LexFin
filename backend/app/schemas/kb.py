"""知识库与文档请求模型（docs/06 §5.3/§5.4）。"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.constants import CATEGORY_SUB


class KbCreateRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=100)
    category: str = Field(..., description="banking/securities/insurance")
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v not in CATEGORY_SUB:
            raise ValueError("分类必须是 banking/securities/insurance")
        return v


class KbUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    status: Optional[int] = Field(None, ge=0, le=1)


class DocumentUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    doc_no: Optional[str] = Field(None, max_length=100)
    doc_type: Optional[str] = Field(None, max_length=20)
    issuing_authority: Optional[str] = Field(None, max_length=100)
    publish_date: Optional[date] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    timeliness: Optional[str] = Field(None, max_length=16)
    keywords: Optional[str] = Field(None, max_length=500)
    is_latest: Optional[int] = Field(None, ge=0, le=1)
    superseded_by: Optional[int] = None


class DocumentListParams(BaseModel):
    kb_id: Optional[int] = None
    category: Optional[str] = None
    status: Optional[str] = None
    doc_type: Optional[str] = None
    timeliness: Optional[str] = None
    keyword: Optional[str] = None
    page: int = 1
    size: int = 10
    sort: Optional[str] = Field("created_at", description="created_at / publish_date")
