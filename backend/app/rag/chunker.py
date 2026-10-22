"""条文感知切分（Chunker，docs/04 §6 ★核心）。

制度文本按「章/节/条」自然边界切分，保证：
1. 每块可溯源到具体条号与页码（answer 溯源要求）；
2. 条内超长时用 RecursiveCharacterTextSplitter 滑窗切分（LangChain，课题指定组件）；
3. 极短条同章相邻合并（article_no 记为区间），不跨章合并；
4. 表格整块保留且带表头前缀（source_type=table）。
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from app.core.config import settings
from app.rag.types import PageContent, ParsedDocument, RawChunk

try:  # LangChain 0.3 生态（课题指定）
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - 兜底，保证纯算法可独立测试
    RecursiveCharacterTextSplitter = None  # type: ignore


# --------------------------------------------------------------------------- #
#  切分单元识别正则（docs/04 §6.1）
# --------------------------------------------------------------------------- #
CN_NUM = r"[一二三四五六七八九十百零〇\d]+"
CHAPTER_RE = re.compile(rf"^(第{CN_NUM}章)(\s+\S.*)?$")
SECTION_RE = re.compile(rf"^(第{CN_NUM}节)(\s+\S.*)?$")
ARTICLE_RE = re.compile(rf"^(第{CN_NUM}条)(.*)$")
ITEM_RE = re.compile(r"^[（(][一二三四五六七八九十\d]+[）)]")
NUM_UNIT_RE = re.compile(r"^\d+(\.\d+){0,3}\s+\S")
ATTACH_RE = re.compile(r"^附\s*(则|件|表)")


@dataclass
class ArticleUnit:
    """一级单元：一个「条」或一个表块。"""

    lines: List[Tuple[str, int]]  # (行文本, 页号)
    chapter_no: Optional[str] = None
    chapter_label: Optional[str] = None  # 完整章标题行，如「第三章 流动性风险管理」
    section_label: Optional[str] = None
    article_no: Optional[str] = None
    source_type: str = "text"
    page_override: Optional[Tuple[int, int]] = None  # 滑窗子块的精确页码跨度

    @property
    def text(self) -> str:
        return "\n".join(t for t, _ in self.lines)

    @property
    def pages(self) -> List[int]:
        return [p for _, p in self.lines]

    @property
    def page_range(self) -> Tuple[int, int]:
        if self.page_override is not None:
            return self.page_override
        pages = self.pages or [1]
        return min(pages), max(pages)


@dataclass
class ChunkerParams:
    chunk_size: int = 500
    chunk_overlap: int = 80
    chunk_max: int = 800
    chunk_min_merge: int = 120

    @classmethod
    def from_settings(cls) -> "ChunkerParams":
        return cls(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            chunk_max=settings.chunk_max,
            chunk_min_merge=settings.chunk_min_merge,
        )


class Chunker:
    def __init__(self, params: Optional[ChunkerParams] = None) -> None:
        self.params = params or ChunkerParams.from_settings()

    # ------------------------------------------------------------------ 入口
    def split(
        self,
        parsed: ParsedDocument,
        doc_title: str = "",
        doc_no: str = "",
    ) -> List[RawChunk]:
        """解析结果 → 切片列表（含 content 前缀、页码、条号）。"""
        units = self._to_units(parsed.pages)
        if not units:
            return []

        has_article = any(u.article_no for u in units if u.source_type != "table")
        if has_article:
            raw_units = self._apply_length_rules(units)
        else:
            raw_units = self._plain_mode(units)

        chunks: List[RawChunk] = []
        for unit in raw_units:
            text = unit.text.strip()
            if not text:
                continue
            page_start, page_end = unit.page_range
            prefix = self.build_prefix(
                doc_title=doc_title,
                doc_no=doc_no,
                chapter_label=unit.chapter_label or unit.chapter_no,
                section_label=unit.section_label,
                article_no=unit.article_no,
            )
            chunks.append(
                RawChunk(
                    raw_content=text,
                    content=f"{prefix}\n{text}",
                    chapter_no=unit.chapter_no,
                    article_no=unit.article_no,
                    page_start=page_start,
                    page_end=page_end,
                    source_type=unit.source_type,
                    char_count=len(text),
                )
            )
        # ⑦ 按顺序赋 chunk_index（0 起）由入库服务写库时处理，这里保持顺序稳定
        return chunks

    # -------------------------------------------------- ① 逐行扫描产出一级单元
    def _to_units(self, pages: Sequence[PageContent]) -> List[ArticleUnit]:
        units: List[ArticleUnit] = []
        current = ArticleUnit(lines=[])
        chapter_no = chapter_label = section_label = None

        def close_current() -> None:
            nonlocal current
            if current.lines:
                units.append(current)
            current = ArticleUnit(
                lines=[],
                chapter_no=chapter_no,
                chapter_label=chapter_label,
                section_label=section_label,
            )

        for page in pages:
            for block in page.blocks:
                if block.type == "table":
                    close_current()
                    units.append(
                        ArticleUnit(
                            lines=[(block.text.strip(), page.page_no)],
                            chapter_no=chapter_no,
                            chapter_label=chapter_label,
                            section_label=section_label,
                            source_type="table",
                        )
                    )
                    continue

                for line in (block.text or "").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    m_ch = CHAPTER_RE.match(line)
                    m_sec = SECTION_RE.match(line)
                    m_art = ARTICLE_RE.match(line)
                    if m_ch:
                        close_current()  # 不跨章
                        chapter_no = m_ch.group(1)
                        chapter_label = line if len(line) <= 40 else m_ch.group(1)
                        section_label = None
                        current.chapter_no = chapter_no
                        current.chapter_label = chapter_label
                        current.section_label = None
                        continue
                    if m_sec:
                        section_label = line if len(line) <= 40 else m_sec.group(1)
                        current.section_label = section_label
                        continue
                    if m_art:
                        close_current()
                        current.article_no = m_art.group(1)
                        current.source_type = "ocr" if block.type == "image_caption" else "text"
                    current.lines.append((line, page.page_no))
        close_current()
        return units

    # ------------------------------------------------------ ② 长度判定与合并
    def _apply_length_rules(self, units: List[ArticleUnit]) -> List[ArticleUnit]:
        p = self.params
        result: List[ArticleUnit] = []
        i = 0
        while i < len(units):
            unit = units[i]
            if unit.source_type == "table":
                result.append(unit)  # ④ 表格整块，不受长度规则限制
                i += 1
                continue
            length = len(unit.text)
            if length > p.chunk_max:
                result.extend(self._split_long_unit(unit))
                i += 1
            elif length >= p.chunk_min_merge:
                result.append(unit)
                i += 1
            else:
                # ③ 极短条：与同章相邻短条合并，直到 ≥ CHUNK_MIN_MERGE；不跨章
                merged = unit
                j = i + 1
                while j < len(units) and len(merged.text) < p.chunk_min_merge:
                    nxt = units[j]
                    if nxt.source_type == "table":
                        break
                    if nxt.chapter_no != unit.chapter_no:
                        break
                    merged = self._merge_units(merged, nxt)
                    j += 1
                result.append(merged)
                i = j
        return result

    @staticmethod
    def _merge_units(a: ArticleUnit, b: ArticleUnit) -> ArticleUnit:
        article_no = a.article_no
        if a.article_no and b.article_no and a.article_no != b.article_no:
            # 区间只保留首尾条号（docs/04 §6.3："第X条~第Y条"）
            start = a.article_no.split("~", 1)[0]
            article_no = f"{start}~{b.article_no}"
        elif b.article_no and not a.article_no:
            article_no = b.article_no
        return ArticleUnit(
            lines=a.lines + b.lines,
            chapter_no=a.chapter_no,
            chapter_label=a.chapter_label,
            section_label=a.section_label,
            article_no=article_no,
            source_type=a.source_type,
        )

    def _split_long_unit(self, unit: ArticleUnit) -> List[ArticleUnit]:
        """条内滑窗切分：每块继承同一 article_no，相邻块有 chunk_overlap 重叠。"""
        p = self.params
        text = unit.text
        pieces = self._recursive_split(text, p.chunk_size, p.chunk_overlap)
        offsets, pages = self._line_offsets(unit)
        out: List[ArticleUnit] = []
        search_from = 0
        for piece in pieces:
            pos = text.find(piece, search_from)
            if pos < 0:
                pos = text.find(piece)
            if pos < 0:
                pos = 0
            search_from = max(search_from, pos + 1)
            page_start, page_end = self._pages_for_span(
                (offsets, pages), pos, pos + len(piece)
            )
            out.append(
                ArticleUnit(
                    lines=[(piece, page_start)],
                    chapter_no=unit.chapter_no,
                    chapter_label=unit.chapter_label,
                    section_label=unit.section_label,
                    article_no=unit.article_no,
                    source_type=unit.source_type,
                    page_override=(page_start, page_end),
                )
            )
        return out

    # ------------------------------------------------------ ③ 无条结构文档
    def _plain_mode(self, units: List[ArticleUnit]) -> List[ArticleUnit]:
        """未识别到「条」结构：按表格边界分段，各段整段递归切分（表格保留原位）。"""
        p = self.params
        out: List[ArticleUnit] = []
        run: List[ArticleUnit] = []

        def flush_run() -> None:
            if not run:
                return
            merged_lines: List[Tuple[str, int]] = []
            for u in run:
                merged_lines.extend(u.lines)
            merged = ArticleUnit(
                lines=merged_lines,
                chapter_no=run[0].chapter_no,
                chapter_label=run[0].chapter_label,
                article_no=None,
            )
            text = merged.text
            offsets, pages = self._line_offsets(merged)
            search_from = 0
            for piece in self._recursive_split(text, p.chunk_size, p.chunk_overlap):
                pos = text.find(piece, search_from)
                if pos < 0:
                    pos = 0
                search_from = max(search_from, pos + 1)
                page_start, page_end = self._pages_for_span(
                    (offsets, pages), pos, pos + len(piece)
                )
                out.append(
                    ArticleUnit(
                        lines=[(piece, page_start)],
                        chapter_no=merged.chapter_no,
                        chapter_label=merged.chapter_label,
                        article_no=None,
                        page_override=(page_start, page_end),
                    )
                )
            run.clear()

        for unit in units:
            if unit.source_type == "table":
                flush_run()
                out.append(unit)  # ④ 表格整块，保留原位
            else:
                run.append(unit)
        flush_run()
        return out

    # ------------------------------------------------------------ 递归切分器
    @staticmethod
    def _recursive_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        separators = ["\n", "。", "；", "，", ""]
        if RecursiveCharacterTextSplitter is not None:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
            )
            return [d.page_content for d in splitter.create_documents([text]) if d.page_content.strip()]
        return _fallback_recursive_split(text, chunk_size, chunk_overlap, separators)

    # ---------------------------------------------------------- 页码映射（⑤）
    @staticmethod
    def _line_offsets(unit: ArticleUnit) -> Tuple[List[int], List[int]]:
        """返回 (每行起始 offset 列表, 每行页号列表)。"""
        offsets: List[int] = []
        pages: List[int] = []
        pos = 0
        for text, page in unit.lines:
            offsets.append(pos)
            pages.append(page)
            pos += len(text) + 1  # '\n'
        return offsets, pages

    @staticmethod
    def _pages_for_span(
        starts: Tuple[List[int], List[int]],
        start_off: int,
        end_off: int,
    ) -> Tuple[int, int]:
        offsets, pages = starts
        if not offsets:
            return 1, 1
        last = len(offsets) - 1
        lo = min(last, max(0, bisect_right(offsets, start_off) - 1))
        hi = min(last, max(lo, bisect_right(offsets, max(start_off, end_off - 1)) - 1))
        span_pages = pages[lo : hi + 1] or [pages[lo]]
        return min(span_pages), max(span_pages)

    # ------------------------------------------------------------ ⑥ 前缀拼装
    @staticmethod
    def build_prefix(
        doc_title: str = "",
        doc_no: str = "",
        chapter_label: Optional[str] = None,
        section_label: Optional[str] = None,
        article_no: Optional[str] = None,
    ) -> str:
        """content 前缀格式（docs/03 §2.4，必须严格遵守）：
        【{doc_title}｜{doc_no}｜{chapter_no} {article_no}】
        """
        parts = [doc_title or "", doc_no or ""]
        struct = " ".join(x for x in (chapter_label, section_label, article_no) if x)
        parts.append(struct)
        return "【" + "｜".join(p for p in parts if p) + "】"

    # ---------------------------------------------------------- ⑧ 切分自检
    @staticmethod
    def self_check(chunks: List[RawChunk], page_count: int = 0) -> List[str]:
        """docs/04 §6.5 切分自检，返回 warning 文本（不阻断入库）。"""
        warnings: List[str] = []
        if not chunks:
            return ["未切分出任何内容"]
        lengths = [len(c.raw_content) for c in chunks]
        if max(lengths) > 2 * settings.chunk_max:
            warnings.append(f"存在超长切片（{max(lengths)} 字），请检查条文正则")
        avg = sum(lengths) / len(lengths)
        if avg < 100:
            warnings.append(f"平均切片长度偏小（{avg:.0f} 字），可能切分过碎")
        has_article_doc = any(c.article_no for c in chunks)
        if has_article_doc:
            ratio = sum(1 for c in chunks if c.article_no) / len(chunks)
            if ratio < 0.3:
                warnings.append("条号识别率低于 30%，请检查正则是否匹配该文体")
        if page_count and len(chunks) > page_count * 40:
            warnings.append("切片数远超页数，可能存在重复内容")
        return warnings


def _fallback_recursive_split(
    text: str, chunk_size: int, chunk_overlap: int, separators: List[str]
) -> List[str]:
    """LangChain 不可用时的等价实现（按分隔符层级递归切分 + 重叠）。"""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    sep = separators[0] if separators else ""
    rest_seps = separators[1:] if len(separators) > 1 else [""]
    parts = text.split(sep) if sep else list(text)
    pieces: List[str] = []
    buffer = ""
    for part in parts:
        candidate = f"{buffer}{sep}{part}" if buffer else part
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue
        if buffer:
            pieces.extend(_fallback_recursive_split(buffer, chunk_size, chunk_overlap, rest_seps))
        buffer = part
    if buffer:
        pieces.extend(_fallback_recursive_split(buffer, chunk_size, chunk_overlap, rest_seps))
    # 相邻块补重叠
    if chunk_overlap > 0 and len(pieces) > 1:
        overlapped: List[str] = [pieces[0]]
        for prev, cur in zip(pieces, pieces[1:]):
            tail = prev[-chunk_overlap:]
            overlapped.append(tail + cur if not cur.startswith(tail) else cur)
        pieces = overlapped
    return [p for p in pieces if p.strip()]


chunker = Chunker()
