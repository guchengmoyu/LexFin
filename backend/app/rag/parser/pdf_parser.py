"""PDF 解析（PyMuPDF 主库，docs/04 §3）。

逐页判定文本层：page_char_count < PDF_TEXT_MIN_CHARS → 该页走 OCR；
全部页需 OCR → parse_method=ocr，部分 → mixed，无 → text；
表格优先 page.find_tables() 转 Markdown，pdfplumber 兜底。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import List

from loguru import logger

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.rag.parser.meta import extract_meta
from app.rag.parser.ocr_engine import ocr_engine
from app.rag.types import PageContent, ParsedDocument, TextBlock

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore


class PdfParser:
    def parse(self, file_path: str) -> ParsedDocument:
        if fitz is None:
            raise BizError(ErrorCode.PARSE_FAILED, "PDF 解析组件 PyMuPDF 未安装")
        path = Path(file_path)
        try:
            doc = fitz.open(str(path))
        except Exception as exc:
            raise BizError(ErrorCode.PARSE_FAILED, "文件已加密或损坏，无法解析") from exc
        if doc.needs_pass:
            raise BizError(ErrorCode.PARSE_FAILED, "文件已加密或损坏，无法解析")

        warnings: List[str] = []
        pages: List[PageContent] = []
        needs_ocr_pages: List[int] = []
        total_chars = 0

        try:
            for page in doc:
                page_no = page.number + 1
                text = page.get_text("text") or ""
                visible = "".join(text.split())
                total_chars += len(visible)

                if len(visible) < settings.pdf_text_min_chars:
                    needs_ocr_pages.append(page_no)
                    continue

                blocks = self._extract_blocks(page, text)
                pages.append(
                    PageContent(
                        page_no=page_no,
                        blocks=blocks,
                        char_count=len(visible),
                        used_ocr=False,
                    )
                )
        finally:
            doc.close()

        # 整体兜底：均值过低强制整份 OCR（docs/04 §3.2）
        page_total = max(1, len(pages) + len(needs_ocr_pages))
        if pages and total_chars / page_total < settings.pdf_text_min_chars_per_page:
            needs_ocr_pages = list(range(1, page_total + 1))
            pages = []

        if needs_ocr_pages:
            ocr_pages = self._ocr_pages(str(path), needs_ocr_pages, warnings)
            by_no = {p.page_no: p for p in pages}
            for p in ocr_pages:
                by_no[p.page_no] = p
            pages = [by_no[n] for n in sorted(by_no)]

        if not pages or all(p.char_count == 0 for p in pages):
            raise BizError(ErrorCode.PARSE_FAILED, "未能从文件中提取到有效文本")

        if needs_ocr_pages and len(needs_ocr_pages) == page_total:
            parse_method = "ocr"
        elif needs_ocr_pages:
            parse_method = "mixed"
        else:
            parse_method = "text"

        full_text = "\n".join(b.text for p in pages for b in p.blocks)
        meta = extract_meta(full_text)
        meta.setdefault("title", path.stem)
        return ParsedDocument(
            file_name=path.name,
            file_ext=path.suffix.lower(),
            pages=pages,
            parse_method=parse_method,  # type: ignore[arg-type]
            meta=meta,
            warnings=warnings,
        )

    # --------------------------------------------------------------- 文本块
    def _extract_blocks(self, page, text: str) -> List[TextBlock]:
        blocks: List[TextBlock] = []
        # 表格探测（PyMuPDF ≥ 1.23）
        table_texts = [
            table_text for table_text in self._extract_tables(page)
            if not self._is_duplicate_page_table(table_text, text)
        ]
        for t in table_texts:
            blocks.append(TextBlock(type="table", text=t, page_no=page.number + 1))
        # 正文按段落边界切块
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                blocks.append(TextBlock(type="text", text=para, page_no=page.number + 1))
        return blocks

    @staticmethod
    def _is_duplicate_page_table(table_text: str, page_text: str) -> bool:
        """Ignore a page-sized layout table that repeats the PDF text layer."""
        def compact(value: str) -> str:
            return re.sub(r"[|｜【】\s:：;；_\-]+", "", value or "")

        page = compact(page_text)
        table = compact(table_text.replace("【表】", ""))
        if not page or len(table) < len(page) * 0.75:
            return False
        return SequenceMatcher(None, page, table, autojunk=False).ratio() >= 0.85

    def _extract_tables(self, page) -> List[str]:
        """表格 → Markdown（保留表头，docs/04 §3.3）。识别失败时返回空，不阻断。"""
        out: List[str] = []
        try:
            finder = page.find_tables()
            for tbl in finder.tables:
                rows = tbl.extract()
                if not rows:
                    continue
                header = rows[0]
                lines = ["【表】", "| " + " | ".join(str(c or "") for c in header) + " |"]
                lines.append("|" + "---|" * len(header))
                for row in rows[1:]:
                    lines.append("| " + " | ".join(str(c or "") for c in row) + " |")
                out.append("\n".join(lines))
        except Exception as exc:
            logger.debug("find_tables 失败，跳过表格抽取: {}", exc)
        return out

    # ------------------------------------------------------------------- OCR
    def _ocr_pages(self, path: str, page_nos: List[int], warnings: List[str]) -> List[PageContent]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.utils.file import md5_file

        out: List[PageContent] = []
        cache_dir = Path(settings.ocr_cache_dir) / md5_file(path)  # docs/04 §4.4
        max_workers = max(1, min(settings.ocr_max_workers, 4))
        with fitz.open(path) as doc, ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._ocr_single_page, doc, pno, cache_dir): pno for pno in page_nos
            }
            for fut in as_completed(futures):
                pno = futures[fut]
                try:
                    out.append(fut.result())
                except Exception as exc:
                    logger.warning("第 {} 页 OCR 失败: {}", pno, exc)
                    warnings.append(f"第 {pno} 页 OCR 失败，已跳过")
        return out

    def _ocr_single_page(self, doc, page_no: int, cache_dir: "Path") -> PageContent:
        import io

        from PIL import Image

        page = doc[page_no - 1]
        pixmap = page.get_pixmap(dpi=settings.ocr_dpi)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        cache = cache_dir / f"p{page_no}.json"
        paragraphs, avg_conf = ocr_engine.ocr_image(image, cache_path=cache)
        text = "\n".join(paragraphs)
        return PageContent(
            page_no=page_no,
            blocks=[TextBlock(type="text", text=text, page_no=page_no)],
            char_count=len("".join(text.split())),
            used_ocr=True,
        )


pdf_parser = PdfParser()
