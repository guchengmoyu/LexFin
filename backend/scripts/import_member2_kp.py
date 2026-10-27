"""按知识点审核批次导入 knowledge_point（含 source_file 扩展名归一化 + 批量发布）。

背景：
- 知识点导入要求 `source_file` 与 `documents.file_name` **完全一致**；
  member2 的 registry 里 5 份是 `.docx`，而 original/ 下实际是 `.pdf`，
  所以导入前按「同名不同扩展」自动改写，避免整批被判「来源文件未入库」。
- 关键词检索与合并后过滤都要求 `status=published AND verify_status=passed`，
  因此 --publish 会把这些 code 批量置为已发布/已通过（导入默认是 draft/pending）。

用法（backend 目录，需 MySQL/Milvus 已启动）：
    # 1) 只看校验结果，不写库
    python -m scripts.import_member2_kp --dry-run --category banking

    # 2) 真导入 + 发布（建议先小批量）
    python -m scripts.import_member2_kp --limit 50 --publish

    # 3) 全量
    python -m scripts.import_member2_kp --publish
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from pathlib import Path

import openpyxl
from sqlalchemy import select, update

from app.db.session import session_scope
from app.models.document import Document
from app.models.knowledge_point import KnowledgePoint
from app.models.user import User
from app.services.knowledge_point import knowledge_point_service as service
from app.utils.time import now

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = ROOT / "data" / "knowledge_points" / "knowledge_points_candidates.xlsx"


def read_rows(path: Path, category: str | None, limit: int | None) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h else "" for h in rows[0]]
    items = []
    for row in rows[1:]:
        item = {}
        for i, key in enumerate(header):
            value = row[i] if i < len(row) else None
            if value is None:
                item[key] = ""
            elif isinstance(value, (int, float)):
                item[key] = str(int(value)) if float(value).is_integer() else str(value)
            else:
                item[key] = str(value).strip()
        if category and item.get("category") != category:
            continue
        items.append(item)
    return items[:limit] if limit else items


def normalize_source_file(items: list[dict], db) -> tuple[list[dict], dict]:
    """把 source_file 的扩展名对齐到库里实际文件名；返回 (处理后行, 统计)。"""
    doc_names = {name for (name,) in db.execute(select(Document.file_name)).all()}
    stems = {os.path.splitext(n)[0]: n for n in doc_names}
    stats = {"total": len(items), "rewritten": 0, "missing": 0, "kept": 0}
    out = []
    for item in items:
        src = (item.get("source_file") or "").strip()
        if not src:
            stats["kept"] += 1
            out.append(item)
            continue
        if src in doc_names:
            stats["kept"] += 1
            out.append(item)
            continue
        stem = os.path.splitext(src)[0]
        actual = stems.get(stem)
        if actual:
            item = dict(item)
            item["source_file"] = actual
            stats["rewritten"] += 1
            out.append(item)
        else:
            stats["missing"] += 1  # 原文没入库，导入时会报「来源文件未入库」
            out.append(item)
    return out, stats


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="导入 member2 知识点批次")
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--kb-id", type=int, default=None, help="覆盖知识库 id（默认按 category 映射）")
    ap.add_argument("--category", choices=["banking", "securities", "insurance"], default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="只校验不写库")
    ap.add_argument("--publish", action="store_true", help="导入后置为 published + verify_status=passed")
    args = ap.parse_args(argv)

    if not args.xlsx.exists():
        print(f"找不到文件：{args.xlsx}")
        return 1

    kb_map = {"banking": 1, "securities": 2, "insurance": 3}
    with session_scope() as db:
        user = db.scalar(select(User).where(User.role == "admin"))
        if user is None:
            print("缺少 admin 用户，请先启动后端完成 seed")
            return 1

        items = read_rows(args.xlsx, args.category, args.limit)
        print(f"读取 {len(items)} 行（category={args.category or '全部'} limit={args.limit or '-'}）")
        items, stats = normalize_source_file(items, db)
        print(
            f"source_file 归一化：保持 {stats['kept']}，扩展名改写 {stats['rewritten']}，库中缺失 {stats['missing']}"
        )
        if stats["rewritten"]:
            sample = [i for i in items if i.get("source_file", "").lower().endswith(".pdf")][:2]
            for s in sample:
                print(f"  例：{s['code']} -> {s['source_file'][:40]}")

        # 标题长度不合法的行（例如抽取残留的「其中」）直接剔除并报告
        bad_title = [i for i in items if not (5 <= len((i.get("title") or "").strip()) <= 300)]
        if bad_title:
            print(f"剔除标题不合法行 {len(bad_title)} 条：{', '.join(str(i.get('code')) for i in bad_title[:8])}")
            items = [i for i in items if i not in bad_title]
        if not items:
            print("没有可导入的数据")
            return 1

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(items[0].keys()))
        writer.writeheader()
        writer.writerows(items)
        payload = buf.getvalue().encode("utf-8-sig")

        # 一个批次只进一个知识库：按 category 分组导入
        groups: dict[int, list[dict]] = {}
        for item in items:
            kb_id = args.kb_id or kb_map.get(item.get("category", ""), 1)
            groups.setdefault(kb_id, []).append(item)

        total_valid = 0
        all_errors: list[dict] = []
        for kb_id, group in groups.items():
            gbuf = io.StringIO()
            w = csv.DictWriter(gbuf, fieldnames=list(group[0].keys()))
            w.writeheader()
            w.writerows(group)
            result = service.import_file(
                db,
                user,
                kb_id,
                f"kp_import_kb{kb_id}.csv",
                gbuf.getvalue().encode("utf-8-sig"),
                dry_run=args.dry_run,
                defer_embedding=not args.dry_run,  # 大批量导入：最后统一分批向量化
            )
            total_valid += int(result.get("valid_rows") or 0)
            all_errors.extend(result.get("errors") or [])
            print(
                f"  kb={kb_id}: 行 {result.get('total_rows')} 有效 {result.get('valid_rows')} "
                f"错误 {len(result.get('errors') or [])} dry_run={result.get('dry_run')}"
            )

        if all_errors:
            from collections import Counter

            print("错误分布：", dict(Counter(e.get("field") for e in all_errors).most_common(6)))
            for e in all_errors[:3]:
                print("  例：", e)

        if args.dry_run:
            print(f"dry-run 完成：有效 {total_valid} 行，未写库")
            return 0

        print(f"导入完成：有效 {total_valid} 行")

        if args.publish:
            codes = [i.get("code") for i in items if i.get("code")]
            updated = db.execute(
                update(KnowledgePoint)
                .where(KnowledgePoint.code.in_(codes))
                .values(status="published", verify_status="passed", verified_by=user.id, verified_at=now())
            ).rowcount
            db.commit()
            print(f"已发布/通过审核：{updated} 条")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
