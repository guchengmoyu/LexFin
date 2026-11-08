"""解析路由（docs/04 §3.1）：按扩展名选择 Parser，统一返回 ParsedDocument。"""
from __future__ import annotations

from pathlib import Path

from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.rag.parser.docx_parser import docx_parser
from app.rag.parser.image_parser import image_parser
from app.rag.parser.pdf_parser import pdf_parser
from app.rag.parser.text_parser import text_parser
from app.rag.types import ParsedDocument

_PARSERS = {
    ".pdf": pdf_parser,
    ".docx": docx_parser,
    ".doc": docx_parser,
    ".txt": text_parser,
    ".md": text_parser,
    ".png": image_parser,
    ".jpg": image_parser,
    ".jpeg": image_parser,
    ".tiff": image_parser,
}


def parse_document(file_path: str) -> ParsedDocument:
    """统一解析入口：不支持的类型 / 解析失败均抛 BizError（docs/04 §8）。"""
    ext = Path(file_path).suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise BizError(
            ErrorCode.FILE_TYPE_NOT_ALLOWED,
            f"不支持的文件类型 {ext or '(无扩展名)'}",
        )
    return parser.parse(file_path)
