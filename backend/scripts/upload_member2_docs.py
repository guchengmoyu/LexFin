"""把 original/ 下的制度原文按 member2 的 document_registry 批量上传入库。

用途：让 knowledge_point 导入时的 source_file / quote_text 能唯一匹配到切片。

用法（backend 目录）：
    python -m scripts.upload_member2_docs --base-url http://127.0.0.1:8002
    python -m scripts.upload_member2_docs --dry-run          # 只打印将要上传的元数据

说明：
- 元数据取自 registry 的 title / doc_no / issuing_authority / timeliness / category；
- 上传接口限流 10 次/分钟，脚本按 7 秒间隔上传；
- 文件名以**实际文件**为准（registry 里 5 个 .docx 实际是 .pdf）；
- kb_id 按 category 映射：banking→1 / securities→2 / insurance→3（可用 --kb-map 覆盖）。
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

import httpx
import openpyxl

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORIGINAL = ROOT / "original"
DEFAULT_REGISTRY = ROOT / "data" / "metadata" / "document_registry.xlsx"
KB_MAP = {"banking": 1, "securities": 2, "insurance": 3}


def load_registry(path: Path) -> dict[str, dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h else "" for h in rows[0]]
    out = {}
    for row in rows[1:]:
        item = {header[i]: row[i] for i in range(min(len(header), len(row)))}
        file_name = (item.get("file_name") or "").strip()
        if not file_name:
            continue
        out[os.path.splitext(file_name)[0]] = item
    return out


def guess_doc_type(title: str) -> str:
    title = title or ""
    if title.endswith("法"):
        return "law"
    if "指引" in title:
        return "guideline"
    if "通知" in title:
        return "notice"
    return "regulation"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="按 registry 批量上传制度原文")
    ap.add_argument("--base-url", default="http://127.0.0.1:8002")
    ap.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="Admin@123")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--interval", type=float, default=7.0, help="上传间隔秒（限流 10 次/分钟）")
    args = ap.parse_args(argv)

    registry = load_registry(args.registry)
    files = sorted(p for p in args.original.glob("*") if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".doc", ".txt"})
    print(f"registry={len(registry)} 条, original={len(files)} 个文件")

    plan = []
    for path in files:
        meta = registry.get(path.stem, {})
        category = (meta.get("category") or "banking").strip()
        kb_id = KB_MAP.get(category, 1)
        title = (meta.get("title") or path.stem).strip()
        plan.append(
            {
                "path": path,
                "kb_id": kb_id,
                "title": title,
                "doc_no": (meta.get("doc_no") or "").strip(),
                "issuing_authority": (meta.get("issuing_authority") or "").strip(),
                "timeliness": (meta.get("timeliness") or "unknown").strip(),
                "doc_type": guess_doc_type(title),
                "matched": bool(meta),
            }
        )

    for p in plan:
        print(
            f"  [{'reg' if p['matched'] else 'raw'}] {p['path'].name} -> kb={p['kb_id']} "
            f"title={p['title'][:28]} doc_no={p['doc_no'][:18]} timeliness={p['timeliness']}"
        )
    if args.dry_run:
        print("dry-run：未上传")
        return 0

    api = f"{args.base_url.rstrip('/')}/api/v1"
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
        resp = client.post(f"{api}/auth/login", json={"username": args.username, "password": args.password})
        resp.raise_for_status()
        token = resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        uploaded = []
        for i, p in enumerate(plan, 1):
            data = {
                "kb_id": str(p["kb_id"]),
                "title": p["title"],
                "doc_type": p["doc_type"],
                "issuing_authority": p["issuing_authority"],
                "timeliness": p["timeliness"],
            }
            if p["doc_no"]:
                data["doc_no"] = p["doc_no"]
            content = p["path"].read_bytes()
            mime = "application/pdf" if p["path"].suffix.lower() == ".pdf" else "application/octet-stream"
            r = client.post(
                f"{api}/documents/upload",
                headers=headers,
                data=data,
                files={"files": (p["path"].name, io.BytesIO(content), mime)},
            )
            if r.status_code != 200:
                print(f"  !! {p['path'].name} HTTP {r.status_code}: {r.text[:200]}")
                continue
            payload = r.json()
            result = (payload.get("data") or {}).get("results", [{}])[0]
            print(
                f"  [{i}/{len(plan)}] {p['path'].name} -> success={result.get('success')} "
                f"doc_id={result.get('document_id')} task={result.get('task_no')} {result.get('message') or ''}"
            )
            uploaded.append(result)
            if i < len(plan):
                time.sleep(args.interval)

        print(f"\n上传完成：{sum(1 for u in uploaded if u.get('success'))}/{len(plan)}")
        tasks = [(u.get("task_no"), u.get("document_id")) for u in uploaded if u.get("task_no")]
        pending = dict(tasks)
        deadline = time.time() + 1800
        while pending and time.time() < deadline:
            time.sleep(5)
            for task_no in list(pending):
                r = client.get(f"{api}/tasks/{task_no}", headers=headers)
                if r.status_code != 200:
                    continue
                t = r.json()["data"]
                if t["status"] in {"success", "failed"}:
                    print(
                        f"  任务 {task_no} doc={pending.pop(task_no)} -> {t['status']} "
                        f"chunks={t.get('total_chunks')} {t.get('error_message') or ''}"
                    )
        if pending:
            print(f"  仍有 {len(pending)} 个任务未完成（可能还在解析），可稍后用 /tasks 查询")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
