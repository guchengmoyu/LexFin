"""认证请求模型（docs/06 §5.1）。"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=4, max_length=50, description="4~50 位字母数字下划线")
    password: str = Field(..., min_length=8, max_length=32, description="8~32 位，含字母与数字")
    real_name: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=100)
    invite_code: Optional[str] = Field(None, max_length=50)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=32)
