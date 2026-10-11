"""全局测试配置（docs/09 §3.2 的单元测试精简版）。

设计要点：
1. 单元测试不依赖 torch / pymilvus / sentence-transformers 等重依赖：
   `app.rag.retriever.hybrid_retriever` 的导入链会拉起 pymilvus，
   这里在测试收集前用惰性 stub 顶掉，保证纯函数（rrf_fuse / dedup_items）可测；
2. 提供确定性 FakeEmbedder / FakeLLM（docs/09 §3.2，可精简，单元测试重点在纯函数）；
3. 提供 ParsedDocument / RetrievedItem / Citation 数据工厂，避免各文件重复构造。
"""
from __future__ import annotations

import sys
import os
from types import ModuleType
from typing import Any, List, Optional, Sequence, Tuple
from unittest import mock

import pytest

# --------------------------------------------------------------------------- #
#  0. pymilvus 惰性 stub（任何属性访问返回 MagicMock，绝不出网/不连接 Milvus）
# --------------------------------------------------------------------------- #
if os.environ.get("LEXFIN_INTEGRATION") != "1" and "pymilvus" not in sys.modules:
    _pymilvus_stub = ModuleType("pymilvus")

    def _fake_attr(name: str) -> Any:
        return mock.MagicMock(name=f"pymilvus.{name}")

    _pymilvus_stub.__getattr__ = _fake_attr  # type: ignore[attr-defined]
    sys.modules["pymilvus"] = _pymilvus_stub

from app.rag.types import (  # noqa: E402  (stub 必须先于 app 导入链生效)
    Citation,
    PageContent,
    ParsedDocument,
    RetrievedItem,
    TextBlock,
)


# --------------------------------------------------------------------------- #
#  1. 确定性 Fake Embedding / Fake LLM（docs/09 §3.2 精简版）
# --------------------------------------------------------------------------- #
class FakeEmbedder:
    """确定性伪向量：相同文本 → 相同向量，相近文本 → 相近向量。"""

    dim = 1024

    def encode(self, texts: List[str]) -> List[List[float]]:
        vecs: List[List[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for i, ch in enumerate(t or ""):
                v[(ord(ch) + i) % self.dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            vecs.append([x / norm for x in v])
        return vecs


class FakeLLM:
    """确定性假大模型：固定返回带角标的答案，支持流式与非流式。"""

    def __init__(self, answer: Optional[str] = None) -> None:
        self.answer = answer or "根据参考条文，该指标应当不低于100%[1]。"

    async def astream(self, messages: Any, **kw: Any) -> Any:
        for ch in self.answer:
            yield ch

    async def ainvoke(self, messages: Any, **kw: Any) -> str:
        return self.answer


@pytest.fixture
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    monkeypatch.setattr("app.rag.embedder.get_embedder", lambda: fake)
    return fake


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr("app.rag.llm.get_llm", lambda **kw: fake)
    return fake


# --------------------------------------------------------------------------- #
#  2. 数据工厂（纯函数，无副作用）
# --------------------------------------------------------------------------- #
def _make_parsed(
    pages: Sequence[Tuple[int, Sequence[Tuple[str, str]]]],
    file_name: str = "sample.docx",
    meta: Optional[dict] = None,
) -> ParsedDocument:
    """pages: [(page_no, [(block_type, block_text), ...]), ...] → ParsedDocument。"""
    return ParsedDocument(
        file_name=file_name,
        file_ext=file_name.rsplit(".", 1)[-1] if "." in file_name else "docx",
        pages=[
            PageContent(
                page_no=page_no,
                blocks=[
                    TextBlock(type=block_type, text=text, page_no=page_no)
                    for block_type, text in blocks
                ],
                char_count=sum(len(t) for _, t in blocks),
                used_ocr=False,
            )
            for page_no, blocks in pages
        ],
        parse_method="text",
        meta=meta or {},
    )


def _make_item(
    source_type: str = "chunk",
    source_id: int = 1,
    kb_id: int = 1,
    document_id: int = 1,
    **kw: Any,
) -> RetrievedItem:
    defaults: dict = dict(
        category="banking",
        timeliness="effective",
        article_no=None,
        page_no=1,
        chunk_index=0,
        content="【测试制度｜测试发〔2024〕1号｜第一条】正文内容",
        raw_content="正文内容",
        title=None,
        doc_title="测试制度",
        doc_no="测试发〔2024〕1号",
        issuing_authority="国家金融监督管理总局",
        chapter_no=None,
        publish_year=2024,
        score=0.0,
    )
    defaults.update(kw)
    return RetrievedItem(
        source_type=source_type,
        source_id=source_id,
        kb_id=kb_id,
        document_id=document_id,
        **defaults,
    )


def _make_citation(cite_index: int = 1, **kw: Any) -> Citation:
    defaults: dict = dict(
        chunk_id=1,
        knowledge_point_id=None,
        document_id=1,
        doc_title="测试制度",
        doc_no="测试发〔2024〕1号",
        issuing_authority="国家金融监督管理总局",
        article_no="第一条",
        page_no=1,
        timeliness="effective",
        snippet="测试摘要",
        score=0.05,
    )
    defaults.update(kw)
    return Citation(cite_index=cite_index, **defaults)


@pytest.fixture
def make_parsed():
    return _make_parsed


@pytest.fixture
def make_item():
    return _make_item


@pytest.fixture
def make_citation():
    return _make_citation
