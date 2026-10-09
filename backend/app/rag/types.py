"""RAG 层公共数据结构（docs/04 §2 统一中间表示、docs/05 §3.4 实体唯一键）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Tuple

# --------------------------------------------------------------------------- #
#  解析中间表示（所有 Parser 必须返回该结构，docs/04 §2）
# --------------------------------------------------------------------------- #
@dataclass
class TextBlock:
    type: Literal["text", "table", "image_caption", "title"]
    text: str
    page_no: int
    bbox: Optional[Tuple[float, float, float, float]] = None  # 高亮定位（二期）
    level: Optional[int] = None  # 标题层级


@dataclass
class PageContent:
    page_no: int
    blocks: List[TextBlock]
    char_count: int
    used_ocr: bool


@dataclass
class ParsedDocument:
    file_name: str
    file_ext: str
    pages: List[PageContent]
    parse_method: Literal["text", "ocr", "mixed"]
    meta: dict  # title / doc_no / issuing_authority / publish_date / effective_date
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  切片（Chunker 产物，入库前形态）
# --------------------------------------------------------------------------- #
@dataclass
class RawChunk:
    raw_content: str  # 无前缀原文
    content: str  # 带元数据前缀（docs/03 §2.4）
    chapter_no: Optional[str]
    article_no: Optional[str]  # 可为区间，如 "第一条~第三条"
    page_start: int
    page_end: int
    source_type: str = "text"  # text / table / ocr
    char_count: int = 0


# --------------------------------------------------------------------------- #
#  检索结果（贯穿 Retriever → RRF → Reranker → Prompt → Citation）
# --------------------------------------------------------------------------- #
@dataclass
class RetrievedItem:
    """检索到的单一证据实体。唯一键 key = f"{source_type}_{source_id}"（与 Milvus pk 一致）。"""

    source_type: str  # chunk / knowledge_point
    source_id: int
    kb_id: int
    document_id: int
    category: str = ""
    timeliness: str = "unknown"
    article_no: Optional[str] = None
    page_no: Optional[int] = None
    chunk_index: int = -1
    content: str = ""  # 带前缀正文（入 Prompt 用）
    raw_content: str = ""  # 无前缀原文（snippet 用）
    title: Optional[str] = None  # 知识点标题；chunk 为 None
    doc_title: Optional[str] = None
    doc_no: Optional[str] = None
    issuing_authority: Optional[str] = None
    chapter_no: Optional[str] = None
    publish_year: int = 0
    score: float = 0.0  # RRF 融合分
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None

    @property
    def key(self) -> str:
        return f"{self.source_type}_{self.source_id}"

    @property
    def content_for_rerank(self) -> str:
        return (self.raw_content or self.content or "")[:512]

    @property
    def knowledge_point_id(self) -> Optional[int]:
        return self.source_id if self.source_type == "knowledge_point" else None

    @property
    def chunk_id(self) -> Optional[int]:
        return self.source_id if self.source_type == "chunk" else None


# --------------------------------------------------------------------------- #
#  引用溯源（docs/05 §8.3 / docs/06 §5.8）
# --------------------------------------------------------------------------- #
@dataclass
class Citation:
    cite_index: int
    chunk_id: Optional[int]
    knowledge_point_id: Optional[int]
    document_id: Optional[int]
    doc_title: Optional[str]
    doc_no: Optional[str]
    issuing_authority: Optional[str]
    article_no: Optional[str]
    page_no: Optional[int]
    timeliness: Optional[str]
    snippet: str
    score: float
    source_url: Optional[str] = None

    @classmethod
    def from_item(cls, item: RetrievedItem, cite_index: int) -> "Citation":
        snippet = (item.raw_content or item.content or "").replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "……"
        doc_id = item.document_id or None
        source_url = f"/api/v1/documents/{doc_id}/download#page={item.page_no}" if doc_id else None
        return cls(
            cite_index=cite_index,
            chunk_id=item.chunk_id,
            knowledge_point_id=item.knowledge_point_id,
            document_id=doc_id,
            doc_title=item.doc_title,
            doc_no=item.doc_no,
            issuing_authority=item.issuing_authority,
            article_no=item.article_no,
            page_no=item.page_no,
            timeliness=item.timeliness,
            snippet=snippet,
            score=round(float(item.score), 5),
            source_url=source_url,
        )

    def to_dict(self) -> dict:
        return {
            "cite_index": self.cite_index,
            "chunk_id": self.chunk_id,
            "knowledge_point_id": self.knowledge_point_id,
            "document_id": self.document_id,
            "doc_title": self.doc_title,
            "doc_no": self.doc_no,
            "issuing_authority": self.issuing_authority,
            "article_no": self.article_no,
            "page_no": self.page_no,
            "timeliness": self.timeliness,
            "snippet": self.snippet,
            "score": self.score,
            "source_url": self.source_url,
        }
