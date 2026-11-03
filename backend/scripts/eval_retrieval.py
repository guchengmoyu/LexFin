"""口语化提问的检索评测（recall@k / MRR），用于 A/B 对比检索侧改动。

判定口径：Top-k 中存在一条命中「同一部制度 + 同一条号」的切片或知识点，
即视为命中（条号按去空白归一化比较）。

用法（backend 目录下）：
    ./.venv/Scripts/python.exe scripts/eval_retrieval.py --tag baseline
    ./.venv/Scripts/python.exe scripts/eval_retrieval.py --tag instruction --no-synonyms
    ./.venv/Scripts/python.exe scripts/eval_retrieval.py --tag all --rerank

开关（默认取 .env 配置）：
    --no-instruction / --instruction   查询侧指令前缀（bge 官方建议）
    --no-synonyms  / --synonyms        关键词通路口语→术语归一
    --no-expand    / --expand          LLM 检索式扩展
    --no-rerank    / --rerank          CrossEncoder 重排
    --top-k N                          评测截断（默认 10，同时报 @1/@3/@5）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.rag.retriever.hybrid_retriever import HybridRetriever  # noqa: E402
from app.rag.retriever.reranker import rerank as rerank_items  # noqa: E402
from app.rag.query_rewriter import analyze  # noqa: E402
from app.rag.types import RetrievedItem  # noqa: E402


def _norm_article(value: Optional[str]) -> str:
    if not value:
        return ""
    return "".join(str(value).split())


def _hit(item: RetrievedItem, doc_title: str, article_no: str) -> bool:
    return _norm_article(item.article_no) == article_no and (item.doc_title or "") == doc_title


def _same_doc(item: RetrievedItem, doc_title: str) -> bool:
    return (item.doc_title or "") == doc_title


async def evaluate(args: argparse.Namespace) -> Dict:
    rows = [json.loads(line) for line in Path(args.data).open(encoding="utf-8") if line.strip()]
    factory = get_session_factory()
    retriever = HybridRetriever()
    from app.rag.query_expansion import expand_queries, should_expand
    from app.rag.llm import get_llm

    llm = get_llm() if args.expand else None
    ranks: List[int] = []          # 1-based rank of first hit, 0 = miss
    doc_ranks: List[int] = []
    empty = 0
    latencies: List[float] = []

    for idx, row in enumerate(rows, 1):
        question = row["question"]
        doc_title = row["doc_title"]
        article_no = _norm_article(row["article_no"])
        started = time.perf_counter()

        infos = [analyze(question)]
        if args.expand and should_expand(question):
            try:
                for variant in await expand_queries(question, llm):
                    infos.append(analyze(variant))
            except Exception as exc:  # noqa: BLE001
                logger.debug("扩展失败 {}: {}", question, exc)

        with factory() as db:
            items = await retriever.retrieve_multi(db, infos, top_k=args.top_k)
        if args.rerank and items:
            items = rerank_items(question, items, top_n=args.top_k)

        latencies.append((time.perf_counter() - started) * 1000)
        if not items:
            empty += 1
            ranks.append(0)
            doc_ranks.append(0)
            continue

        first_hit = next((i for i, it in enumerate(items, 1) if _hit(it, doc_title, article_no)), 0)
        first_doc = next((i for i, it in enumerate(items, 1) if _same_doc(it, doc_title)), 0)
        ranks.append(first_hit)
        doc_ranks.append(first_doc)
        if args.verbose and first_hit == 0:
            got = [(it.doc_title, it.article_no) for it in items[:3]]
            print(f"MISS {row['id']} {question[:40]}… expect={doc_title}/{article_no} got={got}")

    total = len(rows)

    def rate_at(k: int) -> float:
        return sum(1 for r in ranks if 0 < r <= k) / total if total else 0.0

    result = {
        "tag": args.tag,
        "total": total,
        "hit@1": round(rate_at(1), 4),
        "hit@3": round(rate_at(3), 4),
        "hit@5": round(rate_at(5), 4),
        "hit@10": round(rate_at(10), 4),
        "doc_hit@5": round(sum(1 for r in doc_ranks if 0 < r <= 5) / total, 4) if total else 0.0,
        "mrr": round(sum(1 / r for r in ranks if r > 0) / total, 4) if total else 0.0,
        "empty_rate": round(empty / total, 4) if total else 0.0,
        "avg_ms": round(sum(latencies) / total, 1) if total else 0.0,
        "config": {
            "instruction": bool(getattr(settings, "embedding_query_instruction", "")),
            "synonyms": bool(getattr(settings, "synonym_enabled", False)),
            "expand": args.expand,
            "rerank": bool(getattr(settings, "rerank_enabled", False)),
            "keyword": getattr(settings, "keyword_backend", "mysql"),
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tests/data/eval_colloquial.jsonl")
    parser.add_argument("--tag", default="run")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--instruction", dest="instruction", action="store_true", default=None)
    parser.add_argument("--no-instruction", dest="instruction", action="store_false")
    parser.add_argument("--synonyms", dest="synonyms", action="store_true", default=None)
    parser.add_argument("--no-synonyms", dest="synonyms", action="store_false")
    parser.add_argument("--synonym-append", dest="append_terms", action="store_true", default=None)
    parser.add_argument("--no-synonym-append", dest="append_terms", action="store_false")
    parser.add_argument("--expand", dest="expand", action="store_true", default=None)
    parser.add_argument("--no-expand", dest="expand", action="store_false")
    parser.add_argument("--rerank", dest="rerank", action="store_true", default=None)
    parser.add_argument("--no-rerank", dest="rerank", action="store_false")
    parser.add_argument(
        "--rerank-keep", action="store_true",
        help="重排后不丢弃低分候选（min_score=0、top_n=--top-k），用于区分「重排排序」与「截断过滤」的效果",
    )
    parser.add_argument(
        "--keyword", choices=["mysql", "bm25", "both"], default=None,
        help="关键词通道后端：mysql=ngram FULLTEXT，bm25=Milvus 2.5 原生 BM25",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    # 运行期覆盖（必须在 embedder 首次加载前设置）
    if args.keyword:
        settings.keyword_backend = args.keyword
    if args.instruction is not None and hasattr(settings, "embedding_query_instruction"):
        settings.embedding_query_instruction = (
            "为这个句子生成表示以用于检索相关文章：" if args.instruction else ""
        )
    if args.synonyms is not None and hasattr(settings, "synonym_enabled"):
        settings.synonym_enabled = args.synonyms
    if args.append_terms is not None:
        settings.synonym_append_terms = args.append_terms
    if args.rerank is not None:
        settings.rerank_enabled = args.rerank
    if args.rerank_keep:
        settings.rerank_min_score = 0.0
        settings.rerank_top_n = args.top_k
    if args.expand is None:
        args.expand = bool(getattr(settings, "query_expansion_enabled", True))

    result = asyncio.run(evaluate(args))
    line = json.dumps(result, ensure_ascii=False)
    print(line)
    if args.out:
        with Path(args.out).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
