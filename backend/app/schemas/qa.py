"""检索与问答请求模型（docs/06 §5.7/§5.8）。参数校验规则与文档一致。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.constants import QUESTION_MAX_LEN, ErrorCode
from app.core.exceptions import BizError


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    mode: str = Field("hybrid", description="keyword/vector/hybrid")
    kb_ids: Optional[List[int]] = None
    categories: Optional[List[str]] = None
    timeliness: Optional[List[str]] = None
    top_k: int = Field(10, ge=1, le=50)
    include_knowledge_points: bool = True
    include_chunks: bool = True

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in {"keyword", "vector", "hybrid"}:
            raise ValueError("mode 必须是 keyword/vector/hybrid")
        return v

    @field_validator("kb_ids")
    @classmethod
    def _check_kb_ids(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v and len(v) > 5:
            raise ValueError("kb_ids 最多 5 个")
        return v


class QaAskRequest(BaseModel):
    question: str = Field(..., description="1~500 字，去空白后校验")
    session_no: Optional[str] = Field(None, max_length=40)
    kb_ids: Optional[List[int]] = None
    categories: Optional[List[str]] = None
    timeliness: Optional[List[str]] = None
    mode: str = "hybrid"
    top_k: int = Field(5, ge=1, le=10)
    stream: bool = True
    use_history: bool = True

    @field_validator("question")
    @classmethod
    def _check_question(cls, v: str) -> str:
        q = (v or "").strip()
        if not q:
            raise BizError(ErrorCode.QUESTION_EMPTY, "问题内容为空或非法")
        if len(q) > QUESTION_MAX_LEN:
            raise BizError(ErrorCode.QUESTION_TOO_LONG, "问题超长（最多 500 字）")
        return q

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in {"keyword", "vector", "hybrid"}:
            raise ValueError("mode 必须是 keyword/vector/hybrid")
        return v

    @field_validator("kb_ids")
    @classmethod
    def _check_kb_ids(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v and len(v) > 5:
            raise ValueError("kb_ids 最多 5 个")
        return v
