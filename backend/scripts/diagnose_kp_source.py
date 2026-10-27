"""诊断知识点导入的「source 匹配失败」：看清是哪种原因导致 0 命中。

只读脚本，不写库、不改文件。

用法（backend 目录）：
    python -m scripts.diagnose_kp_source --category banking
    python -m scripts.diagnose_kp_source --category banking --show 40
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher

import openpyxl
from sqlalchemy import select

from app.db.session import session_scope
from app.models.chunk import DocumentChunk
from app.models.document import Document

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_XLSX = os.path.join(ROOT, "data", "knowledge_points", "knowledge_points_candidates.xlsx")

PUNCT_RE = re.compile(r"[\s，。、；：？！“”‘’（）《》〈〉【】…—\-·,.;:?!\"'()\[\]<>/\\|_+=~`*&^%$#@]+")


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def norm_plain(text: str) -> str:
    """更激进：去空白 + 去标点（仅用于诊断，判断是否是标点差异）"""
    return PUNCT_RE.sub("", unicodedata.normalize("NFKC", text or ""))


def read_rows(xlsx: str, category: str | None):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h else "" for h in rows[0]]
    out = []
    for row in rows[1:]:
        item = {}
        for i, key in enumerate(header):
            v = row[i] if i < len(row) else None
            item[key] = "" if v is None else (str(v).strip() if not isinstance(v, (int, float)) else str(v))
        if category and item.get("category") != category:
            continue
        out.append(item)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=DEFAULT_XLSX)
    ap.add_argument("--category", default="banking")
    ap.add_argument("--show", type=int, default=40, help="最多打印多少条失败明细")
    args = ap.parse_args(argv)

    rows = read_rows(args.xlsx, args.category)
    print(f"读取 {len(rows)} 行（category={args.category}）")

    with session_scope() as db:
        docs = {d.file_name: d for d in db.scalars(select(Document)).all()}
        stems = {os.path.splitext(n)[0]: n for n in docs}
        chunks_by_doc: dict[int, list] = {}

        def get_chunks(doc_id: int):
            if doc_id not in chunks_by_doc:
                chunks_by_doc[doc_id] = list(
                    db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                               .order_by(DocumentChunk.chunk_index)).all()
                )
            return chunks_by_doc[doc_id]

        stats = {"strict_1": 0, "strict_n": 0, "joined": 0, "punct": 0, "article": 0, "fuzzy": 0, "none": 0, "title_bad": 0}
        printed = 0
        for item in rows:
            title = (item.get("title") or "").strip()
            if not (5 <= len(title) <= 300):
                stats["title_bad"] += 1
                if printed < args.show:
                    print(f"[TITLE] code={item.get('code')} len={len(title)} title={title!r}")
                    printed += 1
                continue
            src = (item.get("source_file") or "").strip()
            quote = item.get("quote_text") or ""
            if not src or not quote:
                continue
            name = src if src in docs else stems.get(os.path.splitext(src)[0])
            if name is None:
                stats["none"] += 1
                if printed < args.show:
                    print(f"[NO-DOC] code={item.get('code')} source_file={src}")
                    printed += 1
                continue
            doc = docs[name]
            chunks = get_chunks(doc.id)
            q = norm_ws(quote)
            matches = [c for c in chunks if q and q in norm_ws(c.raw_content)]
            if len(matches) == 1:
                stats["strict_1"] += 1
                continue
            if len(matches) > 1:
                stats["strict_n"] += 1
                continue

            # 0 命中：依次诊断
            reasons = []
            # 1) 相邻切片拼接能否命中（跨切片）
            joined_hit = False
            texts = [(c.chunk_index, norm_ws(c.raw_content)) for c in chunks]
            for i in range(len(texts) - 1):
                if q in texts[i][1] + texts[i + 1][1]:
                    joined_hit = True
                    break
            if joined_hit:
                reasons.append("跨切片")
            # 2) 忽略标点后能否命中
            qp = norm_plain(quote)
            punct_hits = [c for c in chunks if qp and qp in norm_plain(c.raw_content)]
            if punct_hits:
                reasons.append(f"标点差异({len(punct_hits)})")
            # 3) 条号能否定位
            art = (item.get("article_no") or "").strip()
            art_hit = [c for c in chunks if art and (art in (c.article_no or "") or art in norm_ws(c.raw_content))]
            if art_hit:
                reasons.append(f"条号可定位({len(art_hit)})")
            # 4) 模糊相似度（粗）——比较 quote 首 60 字与每个切片的前 500 字
            best = 0.0
            head = q[:60]
            for c in chunks:
                cand = norm_ws(c.raw_content)[:400]
                if not cand:
                    continue
                best = max(best, SequenceMatcher(None, head, cand).find_longest_match(0, len(head), 0, len(cand)).size / max(1, len(head)))
            if best >= 0.6:
                reasons.append(f"模糊{best:.0%}")
                stats["fuzzy"] += 1
            elif joined_hit:
                stats["joined"] += 1
            elif punct_hits:
                stats["punct"] += 1
            elif art_hit:
                stats["article"] += 1
            else:
                stats["none"] += 1

            if printed < args.show:
                printed += 1
                print(
                    f"[MISS] {item.get('code')} doc={name[:26]} art={art} qlen={len(q)} "
                    f"原因={'/'.join(reasons) or '完全找不到'} qhead={q[:36]}"
                )

    print("\n统计：", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
