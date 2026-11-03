"""构造「口语化提问」检索评测集（docs/09 评测基线）。

思路：从已入库的 1225 条知识点里分层抽样，用 LLM 把每条条文改写成
「普通人会怎么问」的口语问题，从而得到带标准答案（doc_title + article_no）
的评测集。这样就不必人工写 60 条问题，也不会把法条原文混进 query。

用法（backend 目录下）：
    ./.venv/Scripts/python.exe scripts/build_eval_set.py --per-kb 20
输出：backend/tests/data/eval_colloquial.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger  # noqa: E402
from sqlalchemy import text as sql_text  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.rag.llm import get_llm  # noqa: E402

PROMPT = """下面是一条金融监管制度条文。请把它改写成一句「普通人会怎么问」的口语问题：
- 使用日常说法，不要出现法条术语（如"本办法""第X条""适用本法"）
- 不要直接照抄条文里的数字罗列，把数字改成一个疑问（如"最低是多少"）
- 20~40 字，只输出这一句问题，不要解释、不要编号

条文：{content}"""


def sample_rows(per_kb: int, seed: int) -> List[Dict]:
    factory = get_session_factory()
    with factory() as db:
        rows = db.execute(
            sql_text(
                """
                SELECT k.id, k.code, k.kb_id, k.title, k.content, k.article_no,
                       d.title AS doc_title
                FROM knowledge_point k
                JOIN document d ON d.id = k.primary_document_id
                WHERE k.status = 'published' AND k.verify_status = 'passed'
                  AND k.article_no IS NOT NULL AND k.article_no <> ''
                  AND CHAR_LENGTH(k.content) BETWEEN 80 AND 420
                ORDER BY k.id
                """
            )
        ).mappings().all()

    by_kb: Dict[int, List[Dict]] = {}
    seen_article = set()
    for r in rows:
        key = (r["doc_title"], r["article_no"])
        if key in seen_article:
            continue
        seen_article.add(key)
        by_kb.setdefault(int(r["kb_id"]), []).append(dict(r))

    rng = random.Random(seed)
    picked: List[Dict] = []
    for kb_id in sorted(by_kb):
        pool = by_kb[kb_id]
        picked.extend(rng.sample(pool, min(per_kb, len(pool))))
    return picked


async def rewrite(llm, row: Dict, sem: asyncio.Semaphore, idx: int) -> Dict | None:
    content = " ".join(str(row["content"]).split())[:400]
    async with sem:
        try:
            answer = await llm.ainvoke(
                PROMPT.format(content=content), temperature=0.3, max_tokens=120
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("改写失败 id={}: {}", row["id"], exc)
            return None
    question = " ".join(str(answer).strip().split())
    if len(question) < 6:
        return None
    return {
        "id": f"EV-{idx:04d}",
        "question": question.strip("“”\"'"),
        "kb_id": int(row["kb_id"]),
        "doc_title": row["doc_title"],
        "article_no": row["article_no"],
        "kp_code": row["code"],
        "kp_id": int(row["id"]),
        "kp_title": row["title"],
    }


async def main_async(args: argparse.Namespace) -> int:
    rows = sample_rows(args.per_kb, args.seed)
    logger.info("抽样 {} 条知识点（每库 {} 条）", len(rows), args.per_kb)
    llm = get_llm()
    sem = asyncio.Semaphore(5)
    tasks = [rewrite(llm, r, sem, i) for i, r in enumerate(rows, 1)]
    results = [r for r in await asyncio.gather(*tasks) if r]
    results.sort(key=lambda x: x["id"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    logger.info("写入 {} 条 → {}", len(results), out)
    for item in results[:5]:
        print(f"  {item['id']}  {item['question']}  →  {item['doc_title']} {item['article_no']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-kb", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="tests/data/eval_colloquial.jsonl")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
