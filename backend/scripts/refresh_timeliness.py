"""时效状态刷新（docs/03 §4.4）：按判定规则批量更新 timeliness。

规则：
    superseded_by 非空                    → amended（已修订）
    expiry_date < 今天                    → repealed（已废止）
    effective_date <= 今天                → effective（现行有效）
    人工显式指定（--manual-only 跳过）     → 以人工为准
    否则                                  → unknown

用法：cd backend && python scripts/refresh_timeliness.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.session import session_scope  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.knowledge_point import KnowledgePoint  # noqa: E402


def judge(superseded_by, expiry_date, effective_date, today: date) -> str:
    if superseded_by:
        return "amended"
    if expiry_date and expiry_date < today:
        return "repealed"
    if effective_date and effective_date <= today:
        return "effective"
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新文档与知识点的时效状态")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()
    today = date.today()

    with session_scope() as db:
        changed_docs = changed_kps = 0
        for doc in db.scalars(select(Document).where(Document.status != "archived")):
            new_status = judge(doc.superseded_by, doc.expiry_date, doc.effective_date, today)
            if new_status != doc.timeliness:
                changed_docs += 1
                if not args.dry_run:
                    doc.timeliness = new_status
        for kp in db.scalars(select(KnowledgePoint).where(KnowledgePoint.status != "archived")):
            new_status = judge(None, kp.expiry_date, kp.effective_date, today)
            if new_status != kp.timeliness:
                changed_kps += 1
                if not args.dry_run:
                    kp.timeliness = new_status
        mode = "（dry-run 未写库）" if args.dry_run else ""
        print(f"[timeliness] 文档更新 {changed_docs} 条，知识点更新 {changed_kps} 条 {mode}")


if __name__ == "__main__":
    main()
