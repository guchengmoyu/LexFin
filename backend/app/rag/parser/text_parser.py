"""纯文本解析（.txt / .md，docs/04 §3.1）。按空行分段，Markdown 保留标题层级。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.rag.parser.meta import extract_meta
from app.rag.types import PageContent, ParsedDocument, TextBlock

MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


class TextParser:
    def parse(self, file_path: str) -> ParsedDocument:
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="gbk", errors="ignore")
        if not text.strip():
            raise BizError(ErrorCode.PARSE_FAILED, "未能从文件中提取到有效文本")

        blocks: List[TextBlock] = []
        is_md = path.suffix.lower() == ".md"
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if is_md:
                m = MD_HEADING_RE.match(para.splitlines()[0])
                if m:
                    blocks.append(
                        TextBlock(type="title", text=para, page_no=1, level=len(m.group(1)))
                    )
                    continue
            blocks.append(TextBlock(type="text", text=para, page_no=1))

        if not blocks:
            raise BizError(ErrorCode.PARSE_FAILED, "未能从文件中提取到有效文本")

        page = PageContent(
            page_no=1,
            blocks=blocks,
            char_count=sum(len(b.text) for b in blocks),
            used_ocr=False,
        )
        meta = extract_meta(text)
        meta.setdefault("title", path.stem)
        return ParsedDocument(
            file_name=path.name,
            file_ext=path.suffix.lower(),
            pages=[page],
            parse_method="text",
            meta=meta,
            warnings=[],
        )


text_parser = TextParser()
