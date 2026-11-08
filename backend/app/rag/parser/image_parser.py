"""图片解析（.png/.jpg/.jpeg/.tiff → Tesseract OCR，docs/04 §3.1/§4）。"""
from __future__ import annotations

from pathlib import Path
from typing import List

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.rag.parser.meta import extract_meta
from app.rag.parser.ocr_engine import ocr_engine
from app.rag.types import PageContent, ParsedDocument, TextBlock
from app.utils.file import md5_file

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore


class ImageParser:
    def parse(self, file_path: str) -> ParsedDocument:
        if Image is None:
            raise BizError(ErrorCode.OCR_UNAVAILABLE, "OCR 引擎不可用：Pillow 未安装")
        ok, detail = ocr_engine.available()
        if not ok:
            raise BizError(ErrorCode.OCR_UNAVAILABLE, f"OCR 引擎不可用：{detail}")

        path = Path(file_path)
        image = Image.open(str(path))
        cache = Path(settings.ocr_cache_dir) / md5_file(str(path)) / "p1.json"
        paragraphs, avg_conf = ocr_engine.ocr_image(image, cache_path=cache)
        text = "\n".join(paragraphs)
        if not text.strip():
            raise BizError(ErrorCode.PARSE_FAILED, "未能从图片中识别到有效文本")

        blocks: List[TextBlock] = [
            TextBlock(type="text", text=p, page_no=1) for p in paragraphs if p.strip()
        ]
        warnings: List[str] = []
        quality_warning = ocr_engine.quality_check(text, avg_conf)
        if quality_warning:
            warnings.append(quality_warning)

        meta = extract_meta(text)
        meta.setdefault("title", path.stem)
        return ParsedDocument(
            file_name=path.name,
            file_ext=path.suffix.lower(),
            pages=[PageContent(page_no=1, blocks=blocks, char_count=len(text), used_ocr=True)],
            parse_method="ocr",
            meta=meta,
            warnings=warnings,
        )


image_parser = ImageParser()
