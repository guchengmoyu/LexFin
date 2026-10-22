"""通用请求模型：分页、排序（docs/06 §1）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PageParams(BaseModel):
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    size: int = Field(10, ge=1, le=100, description="每页条数 1~100")

    @field_validator("page")
    @classmethod
    def _check_page(cls, v: int) -> int:
        if v < 1:
            raise ValueError("分页参数越界")
        return v


class OkResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Optional[dict] = None
