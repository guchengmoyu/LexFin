"""收藏 / 反馈 / 人工校验请求模型（docs/06 §5.10/§5.11）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class FavoriteCreate(BaseModel):
    message_id: int
    note: Optional[str] = Field(None, max_length=500)


class FavoriteUpdate(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


class FeedbackCreate(BaseModel):
    rating: int = Field(..., description="1 点赞 / -1 点踩")
    reason: Optional[str] = Field(None, max_length=50)
    comment: Optional[str] = Field(None, max_length=1000)

    @field_validator("rating")
    @classmethod
    def _check_rating(cls, v: int) -> int:
        if v not in (1, -1):
            raise ValueError("rating 只能是 1 或 -1")
        return v


class ReviewCreate(BaseModel):
    target_type: str = Field(..., description="answer / knowledge_point")
    target_id: int
    is_correct: int = Field(..., ge=0, le=1)
    error_type: Optional[str] = Field(None, max_length=32)
    comment: Optional[str] = Field(None, max_length=1000)
    batch_no: Optional[str] = Field(None, max_length=40)

    @field_validator("target_type")
    @classmethod
    def _check_target(cls, v: str) -> str:
        if v not in {"answer", "knowledge_point"}:
            raise ValueError("target_type 只能是 answer 或 knowledge_point")
        return v

    @field_validator("error_type")
    @classmethod
    def _check_error_type(cls, v: Optional[str]) -> Optional[str]:
        if v and v not in {
            "retrieval_miss", "hallucination", "citation_wrong", "outdated", "incomplete",
        }:
            raise ValueError("error_type 取值非法")
        return v
