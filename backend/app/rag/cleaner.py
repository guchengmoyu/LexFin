"""文本清洗（Cleaner，docs/04 §5）。

输入解析中间表示 ParsedDocument，输出清洗后的页/行序列；
页眉页脚、断行、全半角、乱码、重复行按规则处理。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Tuple

from app.rag.types import PageContent, ParsedDocument, TextBlock
from app.utils.text import (
    collapse_whitespace,
    is_page_number_line,
    normalize_text,
    strip_invisible,
)

HEADER_FOOTER_MAX_LEN = 40  # 首/末行长度 < 40 才可能是页眉页脚
HEADER_FOOTER_PAGE_RATIO = 0.6  # 出现在 ≥60% 页面才判定为页眉页脚
MIN_BLOCK_LEN = 10  # 清洗后长度 < 10 的块丢弃


class Cleaner:
    """纯函数式清洗器：可对整份文档或单页文本调用。"""

    # -------------------------------------------------------------- 页眉页脚
    @staticmethod
    def _normalize(raw: str) -> str:
        """与 clean_lines 同口径归一（NFKC + 去不可见 + 空白归一），
        保证 find_repeated_lines 的统计与 clean_lines 的比较基准一致。"""
        return collapse_whitespace(normalize_text(strip_invisible(raw))).strip()

    def find_repeated_lines(self, pages: List[PageContent]) -> set[str]:
        """统计出现在 ≥60% 页面首行/末行的短文本，判定为页眉页脚。"""
        if not pages:
            return set()
        head_counter: Counter[str] = Counter()
        tail_counter: Counter[str] = Counter()
        for page in pages:
            texts = [self._normalize(b.text) for b in page.blocks if b.text.strip()]
            if not texts:
                continue
            head_counter[texts[0]] += 1
            tail_counter[texts[-1]] += 1

        threshold = max(1, int(len(pages) * HEADER_FOOTER_PAGE_RATIO))
        result: set[str] = set()
        for counter in (head_counter, tail_counter):
            for text, cnt in counter.items():
                if cnt >= threshold and 0 < len(text) < HEADER_FOOTER_MAX_LEN:
                    result.add(text)
        return result

    # ------------------------------------------------------------------ 行级
    def clean_lines(self, lines: List[str], repeated: set[str] | None = None) -> List[str]:
        """逐行清洗 + 断行合并（docs/04 §5 表格规则）。"""
        repeated = repeated or set()
        out: List[str] = []
        last_line: str = ""
        for raw in lines:
            line = normalize_text(strip_invisible(raw)).rstrip()
            line = collapse_whitespace(line).strip()
            if not line:
                continue
            if is_page_number_line(line):
                continue
            if line in repeated:
                continue
            if line == last_line:
                continue  # 同页内重复行（水印/骑缝章）去重
            last_line = line
            out.append(self._merge_broken_line(out, line))
        # 同页内去重复行（水印/骑缝章）
        deduped: List[str] = []
        for line in out:
            if not deduped or deduped[-1] != line:
                deduped.append(line)
        return deduped

    @staticmethod
    def _merge_broken_line(out: List[str], line: str) -> str:
        """中文行尾非标点且下一行首非标点 → 直接拼接（不加空格）。"""
        if not out:
            return line
        prev = out.pop()
        if prev.endswith("-") and re.match(r"^[a-zA-Z]", line):
            return prev[:-1] + line  # 英文连字符断行
        if prev and prev[-1] not in "。！？；：,.;:!?）)]】》\"'" and line and line[0] not in "（(【《\"'":
            return prev + line
        return prev + "\n" + line

    # ------------------------------------------------------------------ 文档级
    def clean_parsed(self, parsed: ParsedDocument) -> ParsedDocument:
        """结构化清洗：返回清洗后的 ParsedDocument（保留块类型与页号），
        供 Chunker 切分（Parser → Cleaner → Chunker，docs/04 §2）。"""
        repeated = self.find_repeated_lines(parsed.pages)
        pages: List[PageContent] = []
        for page in parsed.pages:
            blocks = []
            for block in page.blocks:
                if block.type == "table":
                    text = self._clean_table(block.text)
                    if text.strip():
                        blocks.append(
                            TextBlock(
                                type="table", text=text, page_no=block.page_no,
                                bbox=block.bbox, level=block.level,
                            )
                        )
                    continue
                raw_lines = (block.text or "").splitlines() or [block.text or ""]
                cleaned = self.clean_lines(raw_lines, repeated)
                text = "\n".join(cleaned)
                if block.type != "title" and len(text.strip()) < MIN_BLOCK_LEN:
                    continue  # 清洗后过短的块丢弃
                if text.strip():
                    blocks.append(
                        TextBlock(
                            type=block.type, text=text, page_no=block.page_no,
                            bbox=block.bbox, level=block.level,
                        )
                    )
            pages.append(
                PageContent(
                    page_no=page.page_no,
                    blocks=blocks,
                    char_count=sum(len(b.text) for b in blocks),
                    used_ocr=page.used_ocr,
                )
            )
        return ParsedDocument(
            file_name=parsed.file_name,
            file_ext=parsed.file_ext,
            pages=pages,
            parse_method=parsed.parse_method,
            meta=parsed.meta,
            warnings=list(parsed.warnings),
        )

    @staticmethod
    def _clean_table(text: str) -> str:
        """表格清洗：逐行归一空白，保留 | 结构与表头。"""
        lines = []
        for raw in (text or "").splitlines():
            line = collapse_whitespace(normalize_text(strip_invisible(raw))).strip()
            if line:
                lines.append(line)
        return "\n".join(lines)

    def clean_document(self, parsed: ParsedDocument) -> List[Tuple[str, int]]:
        """返回清洗后的 (行文本, 页号) 序列（预览/自检用途）。"""
        cleaned = self.clean_parsed(parsed)
        result: List[Tuple[str, int]] = []
        for page in cleaned.pages:
            for block in page.blocks:
                for sub in block.text.splitlines():
                    if sub.strip():
                        result.append((sub.strip(), page.page_no))
        return result


cleaner = Cleaner()
