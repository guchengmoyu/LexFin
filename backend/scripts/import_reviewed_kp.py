"""把「成员1_知识点审核.xlsx」中已人工审核的知识点导入 MySQL `knowledge_point`。

设计取舍（联调期）：
  * 只依赖 openpyxl + PyMySQL，不引 sentence-transformers / pymilvus，
    在没有 Milvus、没有 LLM Key 的机器上也能跑通数据侧联调。
  * verify_status 原样保留（passed / doubted / rejected），不做任何"美化"。
  * status 规则：verify_status == 'passed' -> 'published'（进入正式检索），
    其余保持 'draft'。这是 docs/03 AC-01 的统计口径（status='published'）。
  * 幂等：以 code 为唯一键，重复执行走 UPDATE，不会产生重复行。

用法：
    python backend/scripts/import_reviewed_kp.py [--xlsx 路径] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pymysql
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = ROOT / "成员1_知识点审核.xlsx"

DB = dict(host="127.0.0.1", port=3306, user="root", password="123456",
          database="finrag", charset="utf8mb4", autocommit=False)

KB_BY_CATEGORY = {
    "banking": ("banking", "银行监管知识库"),
    "securities": ("securities", "证券行业知识库"),
    "insurance": ("insurance", "保险制度知识库"),
}

# xlsx 表头 -> knowledge_point 字段
COL_MAP = {
    "code": "code", "title": "title", "content": "content",
    "category": "category", "sub_category": "sub_category",
    "doc_no": "doc_no", "issuing_authority": "issuing_authority",
    "article_no": "article_no", "effective_date": "effective_date",
    "expiry_date": "expiry_date", "timeliness": "timeliness",
    "keywords": "keywords", "difficulty": "difficulty",
    "source_type": "source_type", "verify_status": "verify_status",
    "review_note": "verify_comment",
}
# 需要单独读、不在 COL_MAP 的列，仅用于报告
EXTRA_COLS = ("doc_title", "source_file", "page_no", "quote_text", "source_url")


def norm_date(v):
    if v in (None, "", "None"):
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v).strip()[:10]
    return s or None


def norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() != "none" else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        print(f"[ERROR] 找不到审核表: {xlsx}")
        return 2

    wb = load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb["知识点候选"]
    rows = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c else "" for c in next(rows)]
    idx = {name: i for i, name in enumerate(header)}

    missing = [k for k in COL_MAP if k not in idx]
    if missing:
        print(f"[ERROR] 审核表缺少列: {missing}")
        return 2

    records = []
    for row in rows:
        if not row or row[idx["code"]] in (None, ""):
            continue
        rec = {}
        for src, dst in COL_MAP.items():
            v = row[idx[src]]
            rec[dst] = norm_date(v) if dst in ("effective_date", "expiry_date") else norm(v)
        rec["_doc_title"] = norm(row[idx["doc_title"]]) if "doc_title" in idx else None
        rec["_page_no"] = norm(row[idx["page_no"]]) if "page_no" in idx else None
        records.append(rec)

    total = len(records)
    by_verify, by_cat, by_status = {}, {}, {}
    for r in records:
        vs = r.get("verify_status") or "pending"
        r["status"] = "published" if vs == "passed" else "draft"
        by_verify[vs] = by_verify.get(vs, 0) + 1
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    print(f"=== 读取 {xlsx.name} ===")
    print(f"  知识点行数: {total}")
    print(f"  按 verify_status: {by_verify}")
    print(f"  按 category:     {by_cat}")
    print(f"  将写入 status:   {by_status}")
    if args.dry_run:
        print("  --dry-run：不写库")
        return 0

    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            kb_id = {}
            for cat, (code, name) in KB_BY_CATEGORY.items():
                cur.execute("SELECT id FROM knowledge_base WHERE code=%s", (code,))
                r = cur.fetchone()
                if r:
                    kb_id[cat] = r[0]
                else:
                    cur.execute(
                        "INSERT INTO knowledge_base (code,name,category,description) "
                        "VALUES (%s,%s,%s,%s)",
                        (code, name, cat, f"{name}（自动初始化）"))
                    kb_id[cat] = cur.lastrowid
            conn.commit()
            print(f"  knowledge_base: {kb_id}")

            sql = (
                "INSERT INTO knowledge_point "
                "(kb_id,code,title,content,category,sub_category,doc_no,issuing_authority,"
                "article_no,effective_date,expiry_date,timeliness,keywords,difficulty,"
                "source_type,verify_status,verify_comment,status) VALUES "
                "(%(kb_id)s,%(code)s,%(title)s,%(content)s,%(category)s,%(sub_category)s,"
                "%(doc_no)s,%(issuing_authority)s,%(article_no)s,%(effective_date)s,"
                "%(expiry_date)s,%(timeliness)s,%(keywords)s,%(difficulty)s,"
                "%(source_type)s,%(verify_status)s,%(verify_comment)s,%(status)s) "
                "ON DUPLICATE KEY UPDATE title=VALUES(title), content=VALUES(content), "
                "verify_status=VALUES(verify_status), verify_comment=VALUES(verify_comment), "
                "status=VALUES(status), timeliness=VALUES(timeliness)"
            )
            inserted = updated = 0
            for r in records:
                cat = r["category"]
                if cat not in kb_id:
                    print(f"  [跳过] 未知分类: {r['code']} -> {cat}")
                    continue
                payload = dict(r, kb_id=kb_id[cat],
                               difficulty=int(r["difficulty"] or 1),
                               timeliness=r.get("timeliness") or "unknown",
                               source_type=r.get("source_type") or "import")
                cur.execute(sql, payload)
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    updated += 1
            conn.commit()

            cur.execute(
                "SELECT status, verify_status, COUNT(*) FROM knowledge_point "
                "GROUP BY status, verify_status ORDER BY status, verify_status")
            print("=== 入库后分布（knowledge_point）===")
            for s, v, c in cur.fetchall():
                print(f"  status={s:<10} verify_status={v:<9} : {c}")
            cur.execute(
                "SELECT category, COUNT(*) FROM knowledge_point "
                "WHERE status='published' GROUP BY category")
            print("=== 已发布（AC-01 口径 status='published'）按分类 ===")
            pub_total = 0
            for cat, c in cur.fetchall():
                print(f"  {cat:<12} : {c}")
                pub_total += c
            print(f"  合计 published = {pub_total} / 目标 1000")
            print(f"=== 写入统计：新增 {inserted}，更新 {updated} ===")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
