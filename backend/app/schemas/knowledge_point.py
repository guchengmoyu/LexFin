"""知识点请求模型（docs/06 §5.6）。校验规则后端强制执行。"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import CATEGORY_SUB, ErrorCode
from app.core.exceptions import BizError

VALID_CATEGORIES = set(CATEGORY_SUB.keys())


class KnowledgePointCreate(BaseModel):
    kb_id: int
    title: str = Field(..., min_length=5, max_length=300)
    content: str = Field(..., min_length=10, max_length=2000)
    category: str
    sub_category: Optional[str] = Field(None, max_length=50)
    doc_no: Optional[str] = Field(None, max_length=100)
    issuing_authority: Optional[str] = Field(None, max_length=100)
    article_no: Optional[str] = Field(None, max_length=50)
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    timeliness: str = "unknown"
    keywords: Optional[str] = Field(None, max_length=500)
    difficulty: int = Field(1, ge=1, le=3)
    primary_chunk_id: Optional[int] = None
    status: str = "draft"

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError("分类必须是 banking/securities/insurance")
        return v

    @field_validator("sub_category")
    @classmethod
    def _check_sub_category(cls, v: Optional[str], info) -> Optional[str]:
        category = info.data.get("category")
        if v and category and v not in CATEGORY_SUB.get(category, []):
            raise ValueError(f"子分类不属于 {category} 的合法取值")
        return v

    @model_validator(mode="after")
    def _check_dates(self) -> "KnowledgePointCreate":
        if self.effective_date and self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiry_date 必须晚于 effective_date")
        return self


class KnowledgePointUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=5, max_length=300)
    content: Optional[str] = Field(None, min_length=10, max_length=2000)
    category: Optional[str] = None
    sub_category: Optional[str] = None
    doc_no: Optional[str] = None
    issuing_authority: Optional[str] = None
    article_no: Optional[str] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    timeliness: Optional[str] = None
    keywords: Optional[str] = None
    difficulty: Optional[int] = Field(None, ge=1, le=3)
    primary_chunk_id: Optional[int] = None
    status: Optional[str] = None


class VerifyRequest(BaseModel):
    verify_status: str = Field(..., description="passed/doubted/rejected/pending")
    comment: Optional[str] = Field(None, max_length=500)
    confidence: Optional[float] = Field(None, ge=0, le=1)

    @field_validator("verify_status")
    @classmethod
    def _check_status(cls, v: str) -> str:
        if v not in {"passed", "doubted", "rejected", "pending"}:
            raise ValueError("verify_status 取值非法")
        return v


class SourceBindRequest(BaseModel):
    chunk_id: int
    quote_text: Optional[str] = None
    is_primary: int = Field(0, ge=0, le=1)
