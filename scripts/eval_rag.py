#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 准确率评测脚本（批量问答评测）
==================================

对应设计文档：
  - docs/09-测试方案设计.md §6.1（评测集字段）、§6.2（人工判分规范）、§6.3（输出格式）
  - docs/05-RAG核心链路设计.md §13（调优方法论与评测闭环）
  - docs/06-后端接口设计.md §5.7（POST /retrieve）、§5.8（POST /qa/ask 与 /qa/ask/stream）

职责：
  1. 读取评测集 xlsx（默认 data/eval/eval_set.xlsx），逐题调用 POST /qa/ask；
     加 --stream 时走 /qa/ask/stream（SSE），自行解析事件流并统计真实首 token 时延（TTFT）；
  2. 自动计算 Hit@1 / Hit@3 / Hit@5、MRR@5、refusal_accuracy（拒答正确率）、
     citation_rate（引用覆盖率）、latency_p50 / latency_p95（首 token 时延分位数）；
  3. 输出 JSON 报告（含每题明细）；可用 --export-answers 导出 answers xlsx
     （列含 question / answer / citations / doc_no / article_no），供人工判分回填；
  4. 控制台打印 docs/09 §6.3 示例格式的对比报告（含「人工判分（待回填）」占位）；
     回填后可用 --import-scores 汇总 accuracy、Cohen's Kappa 与错误分布。

评测集 xlsx 列（首行为表头）：
  qid / category / question / question_type / difficulty /
  expected_doc_no / expected_article_no / expected_key_points(用 | 分隔) / expected_answer_type

用法示例（docs/09 §6.3）：
  python scripts/eval_rag.py \\
    --dataset data/eval/eval_set.xlsx \\
    --base-url http://localhost:8000/api/v1 \\
    --username admin --password Admin@123 \\
    --mode hybrid --rerank false --top-k 5 \\
    --batch-no EVAL-20250601 \\
    --out reports/eval_20250601.json \\
    --export-answers reports/answers_20250601.xlsx

常用可选参数：
  --stream               走 SSE 流式问答并统计 TTFT（默认非流式 POST /qa/ask）
  --baseline <json>      传入历史评测 JSON，打印「与基线对比」（§6.3）
  --import-scores <xlsx> 读取人工判分回填后的 answers xlsx，汇总 accuracy / Kappa / 错误分布
  --limit N / --qid Q001,Q002   只评测部分题目（调试用）
  --token <jwt>          直接提供 access_token，跳过登录

依赖：Python 3.11+ 标准库 + httpx + openpyxl（仅用于读写 xlsx，延迟导入）。
本脚本是纯 HTTP 客户端，不 import 本项目 app 包。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

try:
    import httpx
except ImportError:  # pragma: no cover - 环境缺依赖时给出中文提示
    print("错误：缺少依赖 httpx，请先执行 `pip install httpx`。", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


class AppError(RuntimeError):
    """脚本级可读错误（统一中文提示）。"""


def percentile(values: Sequence[float], p: float) -> float:
    """最近秩（nearest-rank）分位数，p 取 0~100；空序列返回 0.0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = math.ceil(p / 100 * len(ordered)) - 1
    idx = max(0, min(len(ordered) - 1, idx))
    return round(float(ordered[idx]), 1)


def now_iso() -> str:
    """本地时区 ISO8601 时间戳。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def str2bool(v: str | bool) -> bool:
    """把命令行的 true/false/1/0 等写法转成 bool（用于 --rerank false 这类写法）。"""
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("布尔参数仅接受 true/false（例如 --rerank false）")


def to_bool_cell(v: Any) -> bool | None:
    """把 xlsx 单元格的判分值转成 bool/None（支持中文「正确/错误」等写法）。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("", "nan", "none", "-"):
        return None
    if s in ("1", "true", "y", "yes", "正确", "对", "√", "✓", "correct"):
        return True
    if s in ("0", "false", "n", "no", "错误", "错", "×", "✗", "incorrect", "wrong"):
        return False
    return None


def fmt_pct(x: float | None) -> str:
    """小数按 3 位显示；None 显示占位符。"""
    return "—" if x is None else f"{x:.3f}"


# ---------------------------------------------------------------------------
# SSE 解析（fetch 流式语义：按空行切事件块，解析 event:/data: 行，data 为 JSON）
# ---------------------------------------------------------------------------


@dataclass
class SSEEvent:
    """单个 SSE 事件：事件名 + 原始 data 文本 + JSON 解析结果（解析失败则为 None）。"""

    event: str
    data: str
    payload: Any | None


class SSEParser:
    """增量 SSE 解析器：喂入任意大小的字节块，吐出完整事件。

    - 事件块以空行（\\n\\n 或 \\r\\n\\r\\n）分隔；
    - 支持多行 data（按 \\n 拼接）、注释行（以 ':' 开头，如心跳注释）；
    - 未声明 event: 行时事件名默认 message。
    """

    _BLOCK_SEP = re.compile(r"\r?\n\r?\n")

    def __init__(self) -> None:
        self._buf: str = ""

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        """喂入字节流片段，返回本次解析出的完整事件列表。"""
        self._buf += chunk.decode("utf-8", errors="replace")
        events: list[SSEEvent] = []
        while True:
            m = self._BLOCK_SEP.search(self._buf)
            if not m:
                break
            block, self._buf = self._buf[: m.start()], self._buf[m.end():]
            ev = self._parse_block(block)
            if ev is not None:
                events.append(ev)
        return events

    def flush(self) -> list[SSEEvent]:
        """流结束时把缓冲区里未以空行结尾的残余块也解析掉。"""
        events: list[SSEEvent] = []
        if self._buf.strip():
            ev = self._parse_block(self._buf)
            if ev is not None:
                events.append(ev)
        self._buf = ""
        return events

    @staticmethod
    def _parse_block(block: str) -> SSEEvent | None:
        event_name = "message"
        data_lines: list[str] = []
        for raw in block.splitlines():
            line = raw.rstrip("\r")
            if not line or line.startswith(":"):
                continue  # 空行/注释（心跳注释）直接忽略
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
            # 其余字段（id:/retry:）本脚本不关心
        if not data_lines and event_name == "message":
            return None
        data = "\n".join(data_lines)
        payload: Any | None
        try:
            payload = json.loads(data) if data else None
        except json.JSONDecodeError:
            payload = None  # data 非 JSON 时保留原文，由调用方决定如何处理
        return SSEEvent(event=event_name, data=data, payload=payload)


# ---------------------------------------------------------------------------
# HTTP 客户端（纯 HTTP，不 import app 包）
# ---------------------------------------------------------------------------


@dataclass
class StreamResult:
    """一次 SSE 问答的采集结果。"""

    answer_text: str = ""
    ttft_ms: float | None = None  # 忽略 ping 后第一个事件（meta/token 取先到者）
    total_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)
    done: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ApiClient:
    """面向 /api/v1 的最小 HTTP 客户端：登录、检索、问答（含 SSE）。"""

    def __init__(
        self,
        base_url: str,
        username: str | None,
        password: str | None,
        token: str | None,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token = token
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, read=timeout),
            headers={"User-Agent": "FinRAG-eval_rag/1.0"},
            follow_redirects=False,
        )

    # -- 基础设施 ---------------------------------------------------------
    def _url(self, path: str) -> str:
        """拼接 {base_url}/api/v1 下的接口路径（base_url 已含 /api/v1）。"""
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Any:
        """按 docs/06 §2 统一响应结构解包：code==0 返回 data，否则抛出中文错误。"""
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
            raise AppError(
                f"接口响应不是合法 JSON（HTTP {resp.status_code}）：{resp.text[:200]}"
            ) from exc
        code = payload.get("code")
        if resp.status_code >= 400 or (code is not None and code != 0):
            raise AppError(
                f"接口返回错误（HTTP {resp.status_code}, code={code}）："
                f"{payload.get('message')}（request_id={payload.get('request_id')}）"
            )
        return payload.get("data")

    # -- 接口 -------------------------------------------------------------
    def login(self) -> None:
        """POST /auth/login，取 data.access_token（docs/06 §5.1）。"""
        if self.token:
            return
        if not self.username or not self.password:
            raise AppError("缺少凭证：请提供 --username/--password 或 --token。")
        resp = self._client.post(
            self._url("/auth/login"),
            json={"username": self.username, "password": self.password},
        )
        data = self._unwrap(resp)
        token = (data or {}).get("access_token") if isinstance(data, dict) else None
        if not token:
            raise AppError("登录响应中未找到 data.access_token，无法继续评测。")
        self.token = str(token)

    def retrieve(
        self,
        question: str,
        mode: str,
        top_k: int,
        kb_ids: list[int] | None,
    ) -> dict[str, Any]:
        """POST /retrieve：取回排序后的检索结果，用于 Hit@N / MRR@5（docs/06 §5.7）。"""
        body: dict[str, Any] = {
            "query": question,
            "mode": mode,
            "top_k": top_k,
            "include_knowledge_points": True,
            "include_chunks": True,
        }
        if kb_ids:
            body["kb_ids"] = kb_ids
        resp = self._client.post(self._url("/retrieve"), json=body, headers=self._headers())
        data = self._unwrap(resp)
        return data if isinstance(data, dict) else {}

    def ask(
        self,
        question: str,
        mode: str,
        top_k: int,
        kb_ids: list[int] | None,
        rerank: bool | None,
    ) -> dict[str, Any]:
        """POST /qa/ask（非流式），响应 data 含 answer/citations/latency_detail（docs/06 §5.8）。"""
        body: dict[str, Any] = {
            "question": question,
            "session_no": None,
            "kb_ids": kb_ids,
            "categories": None,
            "timeliness": None,
            "mode": mode,
            "top_k": top_k,
            "stream": False,
            "use_history": False,  # 评测要求单轮、无历史污染
        }
        if rerank is not None:
            body["rerank"] = rerank  # 重排开关（docs/05 §4），未指定时不传
        resp = self._client.post(self._url("/qa/ask"), json=body, headers=self._headers())
        data = self._unwrap(resp)
        return data if isinstance(data, dict) else {}

    def ask_stream(
        self,
        question: str,
        mode: str,
        top_k: int,
        kb_ids: list[int] | None,
        rerank: bool | None,
    ) -> StreamResult:
        """POST /qa/ask/stream：自行解析 SSE（meta/token/ping/done/error），统计 TTFT。"""
        body: dict[str, Any] = {
            "question": question,
            "session_no": None,
            "kb_ids": kb_ids,
            "categories": None,
            "timeliness": None,
            "mode": mode,
            "top_k": top_k,
            "stream": True,
            "use_history": False,
        }
        if rerank is not None:
            body["rerank"] = rerank

        result = StreamResult()
        parser = SSEParser()
        start = time.perf_counter()

        def _handle(ev: SSEEvent) -> bool:
            """处理单个事件；返回是否应结束流。"""
            if ev.event == "ping":
                return False  # 心跳忽略，不参与 TTFT
            if result.ttft_ms is None:
                result.ttft_ms = (time.perf_counter() - start) * 1000.0
            payload = ev.payload if isinstance(ev.payload, dict) else {}
            if ev.event == "meta":
                result.meta = payload
            elif ev.event == "token":
                result.answer_text += str(payload.get("delta", ""))
            elif ev.event == "done":
                result.done = payload
                return True
            elif ev.event == "error":
                result.error = (
                    f"服务端返回 error 事件（code={payload.get('code')}）：{payload.get('message')}"
                )
                return True
            return False

        try:
            with self._client.stream(
                "POST", self._url("/qa/ask/stream"), json=body, headers=self._headers()
            ) as resp:
                if resp.status_code >= 400:
                    raw = resp.read().decode("utf-8", errors="replace")
                    try:
                        payload = json.loads(raw)
                        raise AppError(
                            f"流式问答请求失败（HTTP {resp.status_code}, "
                            f"code={payload.get('code')}）：{payload.get('message')}"
                        )
                    except json.JSONDecodeError:
                        raise AppError(
                            f"流式问答请求失败（HTTP {resp.status_code}）：{raw[:200]}"
                        ) from None
                finished = False
                for chunk in resp.iter_bytes():
                    for ev in parser.feed(chunk):
                        if _handle(ev):
                            finished = True
                            break
                    if finished:
                        break
                for ev in parser.flush():
                    _handle(ev)
        except httpx.HTTPError as exc:
            raise AppError(f"流式问答网络错误：{exc}") from exc
        result.total_ms = (time.perf_counter() - start) * 1000.0
        return result


# ---------------------------------------------------------------------------
# 评测集读取
# ---------------------------------------------------------------------------

# 评测集必需列（docs/09 §6.1）；difficulty/expected_* 缺失时按空处理
REQUIRED_COLUMNS = ("qid", "question")
ALL_COLUMNS = (
    "qid",
    "category",
    "question",
    "question_type",
    "difficulty",
    "expected_doc_no",
    "expected_article_no",
    "expected_key_points",
    "expected_answer_type",
)


@dataclass
class EvalItem:
    """评测集一行。"""

    qid: str
    category: str
    question: str
    question_type: str
    difficulty: str
    expected_doc_no: str
    expected_article_no: str
    expected_key_points: list[str]
    expected_answer_type: str


def load_dataset(path: Path) -> list[EvalItem]:
    """读取评测集 xlsx（首行表头），返回题目列表。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise AppError("缺少依赖 openpyxl，请先执行 `pip install openpyxl`。") from exc
    if not path.exists():
        raise AppError(f"评测集文件不存在：{path}")
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise AppError(f"评测集必须是 .xlsx 文件（docs/09 §6.1 约定）：{path}")

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header_row = next(rows, None)
    if not header_row:
        raise AppError(f"评测集为空：{path}")
    header = [str(c).strip() if c is not None else "" for c in header_row]
    col = {name: header.index(name) for name in header if name}
    missing = [c for c in REQUIRED_COLUMNS if c not in col]
    if missing:
        raise AppError(f"评测集缺少必需列：{'、'.join(missing)}（表头实际为：{'、'.join(header)}）")

    def cell(row: Sequence[Any], name: str) -> str:
        idx = col.get(name)
        if idx is None or idx >= len(row) or row[idx] is None:
            return ""
        return str(row[idx]).strip()

    items: list[EvalItem] = []
    for i, row in enumerate(rows, start=2):
        question = cell(row, "question")
        if not question:
            continue  # 跳过空行
        qid = cell(row, "qid") or f"Q{i - 1:03d}"
        key_points_raw = cell(row, "expected_key_points")
        items.append(
            EvalItem(
                qid=qid,
                category=cell(row, "category"),
                question=question,
                question_type=cell(row, "question_type"),
                difficulty=cell(row, "difficulty"),
                expected_doc_no=cell(row, "expected_doc_no"),
                expected_article_no=cell(row, "expected_article_no"),
                expected_key_points=[p.strip() for p in key_points_raw.split("|") if p.strip()],
                expected_answer_type=cell(row, "expected_answer_type").lower(),
            )
        )
    if not items:
        raise AppError(f"评测集没有任何有效题目：{path}")
    return items


# ---------------------------------------------------------------------------
# 单题评测
# ---------------------------------------------------------------------------

_TRIM_KEYS = (
    "rank",
    "source_type",
    "source_id",
    "title",
    "doc_title",
    "doc_no",
    "article_no",
    "page_no",
    "timeliness",
    "score",
    "vector_rank",
    "keyword_rank",
)


def _trim_item(item: dict[str, Any]) -> dict[str, Any]:
    """只保留评测关心的检索结果字段，避免报告过大。"""
    return {k: item.get(k) for k in _TRIM_KEYS if k in item}


def _match_no(expected: str, actual: Any) -> bool:
    """文号/条号匹配：未标注即不限定；标注了则相等或互相包含（兼容全半角/空格差异）。"""
    if not expected:
        return True
    if actual is None:
        return False
    e = expected.strip()
    a = str(actual).strip()
    if not a:
        return False
    return e == a or e in a or a in e


def evaluate_one(client: ApiClient, item: EvalItem, args: argparse.Namespace) -> dict[str, Any]:
    """评测单题：检索（Hit@N/MRR）+ 问答（answer/citations/时延），返回明细记录。"""
    record: dict[str, Any] = {
        "qid": item.qid,
        "category": item.category,
        "question": item.question,
        "question_type": item.question_type,
        "difficulty": item.difficulty,
        "expected_doc_no": item.expected_doc_no,
        "expected_article_no": item.expected_article_no,
        "expected_key_points": item.expected_key_points,
        "expected_answer_type": item.expected_answer_type,
        # 运行结果（失败时保留错误信息，评测继续跑下一题）
        "retrieval_items": [],
        "retrieval_error": None,
        "answer": "",
        "answer_type": None,
        "confidence": None,
        "citations": [],
        "latency_ms": None,
        "latency_detail": None,
        "first_token_ms": None,
        "first_token_source": None,
        "error": None,
        # 自动指标
        "hit@1": None,
        "hit@3": None,
        "hit@5": None,
        "reciprocal_rank": None,
        "refusal_correct": None,
        "has_citation": False,
        # 人工判分占位（docs/09 §6.2，回填后用 --import-scores 汇总）
        "manual": {
            "review_a_correct": None,
            "review_b_correct": None,
            "review_final_correct": None,
            "review_final_error_type": None,
            "note": None,
        },
    }

    # ---- 1) 检索：拿排序结果计算 Hit@N / MRR@5 ------------------------
    items: list[dict[str, Any]] = []
    if not args.no_retrieve:
        try:
            data = client.retrieve(item.question, args.mode, args.retrieve_top_k, args.kb_ids)
            items = [_trim_item(x) for x in (data.get("items") or []) if isinstance(x, dict)]
            record["retrieval_items"] = items
        except AppError as exc:
            record["retrieval_error"] = str(exc)

    need_hit = bool(item.expected_doc_no or item.expected_article_no)
    if need_hit:
        rr = 0.0
        ranks = {1: False, 3: False, 5: False}
        for pos, res in enumerate(items, start=1):
            matched = _match_no(item.expected_doc_no, res.get("doc_no")) and _match_no(
                item.expected_article_no, res.get("article_no")
            )
            if matched:
                if rr == 0.0 and pos <= 5:
                    rr = 1.0 / pos
                for k in ranks:
                    if pos <= k:
                        ranks[k] = True
        record["hit@1"] = ranks[1]
        record["hit@3"] = ranks[3]
        record["hit@5"] = ranks[5]
        record["reciprocal_rank"] = rr

    # ---- 2) 问答 ------------------------------------------------------
    try:
        if args.stream:
            sres = client.ask_stream(item.question, args.mode, args.top_k, args.kb_ids, args.rerank)
            if sres.error:
                raise AppError(sres.error)
            done = sres.done or {}
            meta = sres.meta or {}
            record["answer"] = sres.answer_text.strip()
            record["answer_type"] = done.get("answer_type")
            record["confidence"] = done.get("confidence")
            record["citations"] = meta.get("citations") or []
            record["latency_ms"] = done.get("latency_ms") or round(sres.total_ms, 1)
            record["latency_detail"] = done.get("latency_detail")
            record["first_token_ms"] = round(sres.ttft_ms, 1) if sres.ttft_ms is not None else None
            record["first_token_source"] = "sse_measured"
        else:
            data = client.ask(item.question, args.mode, args.top_k, args.kb_ids, args.rerank)
            record["answer"] = str(data.get("answer") or "").strip()
            record["answer_type"] = data.get("answer_type")
            record["confidence"] = data.get("confidence")
            record["citations"] = data.get("citations") or []
            record["latency_ms"] = data.get("latency_ms")
            detail = data.get("latency_detail")
            record["latency_detail"] = detail
            # 非流式拿不到真实首字节，用 latency_detail 估算端到端首 token：
            # rewrite + retrieve + rerank + llm_ttft（+prompt），缺字段时退化为总时延
            if isinstance(detail, dict) and detail:
                ttft = sum(
                    float(detail.get(k) or 0)
                    for k in ("rewrite", "retrieve", "rerank", "llm_ttft", "prompt")
                )
                record["first_token_ms"] = round(ttft, 1) if ttft > 0 else data.get("latency_ms")
                record["first_token_source"] = "latency_detail"
            else:
                record["first_token_ms"] = data.get("latency_ms")
                record["first_token_source"] = "latency_ms"
    except AppError as exc:
        record["error"] = str(exc)
        return record

    # ---- 3) 自动判定指标 ----------------------------------------------
    if item.expected_answer_type == "refused":
        record["refusal_correct"] = record["answer_type"] == "refused"
    if record["answer_type"] == "answered":
        # 引用覆盖率口径：答案正文含 [n] 角标且至少返回 1 条引用（docs/09 §6.3 citation_rate）
        has_marker = bool(re.search(r"\[\d+\]", record["answer"]))
        record["has_citation"] = has_marker and bool(record["citations"])
    return record


# ---------------------------------------------------------------------------
# 汇总统计
# ---------------------------------------------------------------------------


def cohen_kappa(a: Sequence[bool | None], b: Sequence[bool | None]) -> float | None:
    """二分类 Cohen's Kappa（docs/09 §6.2 双人一致性）。"""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(1 for x, y in pairs if x == y)
    p_o = agree / n
    p_a = sum(1 for x, _ in pairs if x) / n
    p_b = sum(1 for _, y in pairs if y) / n
    p_e = p_a * p_b + (1 - p_a) * (1 - p_b)
    if abs(1 - p_e) < 1e-12:
        return 1.0
    return round((p_o - p_e) / (1 - p_e), 3)


def summarize(
    records: list[dict[str, Any]], args: argparse.Namespace, batch_no: str
) -> dict[str, Any]:
    """汇总自动指标 + 人工判分结果（若已回填）。"""
    ok_records = [r for r in records if not r.get("error")]
    hit_records = [r for r in ok_records if r.get("hit@5") is not None]
    answered = [r for r in ok_records if r.get("answer_type") == "answered"]
    refused_expect = [r for r in ok_records if r["expected_answer_type"] == "refused"]
    ttfts = [float(r["first_token_ms"]) for r in ok_records if r.get("first_token_ms") is not None]

    def mean_bool(rows: Sequence[dict[str, Any]], key: str) -> float | None:
        vals = [1.0 if r.get(key) else 0.0 for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    # 分类 / 难度 / 题型细分布（便于调优定位，docs/05 §13）
    breakdown: dict[str, Any] = {}
    for group_key in ("category", "question_type", "difficulty"):
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in hit_records:
            groups.setdefault(str(r.get(group_key) or "未标注"), []).append(r)
        breakdown[group_key] = {
            g: {"n": len(rows), "hit@5": mean_bool(rows, "hit@5")}
            for g, rows in sorted(groups.items())
        }

    return {
        "batch_no": batch_no,
        "generated_at": now_iso(),
        "config": {
            "dataset": str(args.dataset),
            "base_url": args.base_url,
            "mode": args.mode,
            "rerank": args.rerank,
            "top_k": args.top_k,
            "retrieve_top_k": args.retrieve_top_k,
            "kb_ids": args.kb_ids,
            "stream": args.stream,
        },
        "counts": {
            "total": len(records),
            "ok": len(ok_records),
            "failed": len(records) - len(ok_records),
            "answered": len(answered),
            "refused_expected": len(refused_expect),
        },
        "hit@1": mean_bool(hit_records, "hit@1"),
        "hit@3": mean_bool(hit_records, "hit@3"),
        "hit@5": mean_bool(hit_records, "hit@5"),
        "mrr@5": (
            round(sum(float(r["reciprocal_rank"]) for r in hit_records) / len(hit_records), 3)
            if hit_records
            else None
        ),
        "refusal_accuracy": mean_bool(refused_expect, "refusal_correct"),
        "citation_rate": mean_bool(answered, "has_citation"),
        "latency_p50_ms": percentile(ttfts, 50),
        "latency_p95_ms": percentile(ttfts, 95),
        "latency_p99_ms": percentile(ttfts, 99),
        "latency_max_ms": percentile(ttfts, 100),
        "breakdown": breakdown,
    }


def import_scores(path: Path, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """读取人工判分回填后的 answers xlsx，汇总 accuracy / Kappa / 错误分布（docs/09 §6.2）。"""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise AppError("缺少依赖 openpyxl，请先执行 `pip install openpyxl`。") from exc
    if not path.exists():
        raise AppError(f"人工判分文件不存在：{path}")

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows, ())]
    col = {name: i for i, name in enumerate(header) if name}
    if "qid" not in col:
        raise AppError(f"人工判分文件缺少 qid 列：{path}")

    def cell(row: Sequence[Any], name: str) -> Any:
        idx = col.get(name)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    scores: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = cell(row, "qid")
        if not qid:
            continue
        scores[str(qid).strip()] = {
            "a": to_bool_cell(cell(row, "review_a_correct")),
            "b": to_bool_cell(cell(row, "review_b_correct")),
            "final": to_bool_cell(cell(row, "review_final_correct")),
            "error_type": cell(row, "review_final_error_type"),
        }

    a_list: list[bool | None] = []
    b_list: list[bool | None] = []
    error_types: dict[str, int] = {}
    correct = 0
    scored = 0
    for r in records:
        s = scores.get(str(r.get("qid")))
        if not s:
            continue
        r["manual"] = {
            "review_a_correct": s["a"],
            "review_b_correct": s["b"],
            "review_final_correct": s["final"],
            "review_final_error_type": s["error_type"],
            "note": r.get("manual", {}).get("note"),
        }
        if r["expected_answer_type"] == "refused":
            continue  # 准确率分母不含拒答题（docs/09 §6.2 第 5 条）
        a_list.append(s["a"])
        b_list.append(s["b"])
        if s["final"] is not None:
            scored += 1
            if s["final"]:
                correct += 1
            elif s["error_type"]:
                key = str(s["error_type"]).strip()
                error_types[key] = error_types.get(key, 0) + 1

    if scored == 0:
        return None
    return {
        "accuracy": round(correct / scored, 3),
        "correct": correct,
        "scored": scored,
        "kappa": cohen_kappa(a_list, b_list),
        "annotators": 2,
        "error_types": dict(sorted(error_types.items())),
        "source": str(path),
    }


# ---------------------------------------------------------------------------
# 输出：JSON / answers xlsx / 控制台报告
# ---------------------------------------------------------------------------

EXPORT_HEADERS = [
    "qid",
    "category",
    "question",
    "question_type",
    "difficulty",
    "expected_doc_no",
    "expected_article_no",
    "expected_key_points",
    "expected_answer_type",
    "answer_type",
    "answer",
    "citations",
    "doc_no",
    "article_no",
    "hit@1",
    "hit@3",
    "hit@5",
    "reciprocal_rank",
    "first_token_ms",
    "latency_ms",
    "retrieval_top5",
    "review_a_correct",
    "review_b_correct",
    "review_final_correct",
    "review_final_error_type",
    "review_note",
]


def _citations_text(citations: Sequence[dict[str, Any]]) -> str:
    parts = []
    for c in citations:
        idx = c.get("cite_index")
        no = c.get("doc_no") or c.get("doc_title") or ""
        art = c.get("article_no") or ""
        parts.append(f"[{idx}] {no} {art}".strip())
    return "；".join(parts)


def export_answers(path: Path, records: list[dict[str, Any]]) -> None:
    """导出 answers xlsx：含 question/answer/citations/doc_no/article_no + 人工判分回填列。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError as exc:  # pragma: no cover
        raise AppError("缺少依赖 openpyxl，请先执行 `pip install openpyxl`。") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "answers"
    ws.append(EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for r in records:
        citations = [c for c in (r.get("citations") or []) if isinstance(c, dict)]
        doc_nos = " | ".join(dict.fromkeys(str(c.get("doc_no")) for c in citations if c.get("doc_no")))
        art_nos = " | ".join(
            dict.fromkeys(str(c.get("article_no")) for c in citations if c.get("article_no"))
        )
        top5 = " | ".join(
            f"{it.get('rank')}.{it.get('doc_no') or ''} {it.get('article_no') or ''}".strip()
            for it in (r.get("retrieval_items") or [])[:5]
        )
        manual = r.get("manual") or {}
        ws.append(
            [
                r.get("qid"),
                r.get("category"),
                r.get("question"),
                r.get("question_type"),
                r.get("difficulty"),
                r.get("expected_doc_no"),
                r.get("expected_article_no"),
                "|".join(r.get("expected_key_points") or []),
                r.get("expected_answer_type"),
                r.get("answer_type"),
                r.get("answer"),
                _citations_text(citations),
                doc_nos,
                art_nos,
                r.get("hit@1"),
                r.get("hit@3"),
                r.get("hit@5"),
                r.get("reciprocal_rank"),
                r.get("first_token_ms"),
                r.get("latency_ms"),
                top5,
                manual.get("review_a_correct"),
                manual.get("review_b_correct"),
                manual.get("review_final_correct"),
                manual.get("review_final_error_type"),
                manual.get("note"),
            ]
        )
    wb.save(path)


def print_report(
    summary: dict[str, Any],
    manual: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
) -> None:
    """控制台打印 docs/09 §6.3 示例格式的对比报告。"""
    cfg = summary["config"]
    counts = summary["counts"]
    print()
    print(f"================ 评测结果  batch={summary['batch_no']} ================")
    print(
        f"模式: {cfg['mode']}    重排: {str(cfg['rerank']).lower() if cfg['rerank'] is not None else '默认'}"
        f"    TopK: {cfg['top_k']}    题目: {counts['total']}"
        + (f"    （成功 {counts['ok']}，失败 {counts['failed']}）" if counts["failed"] else "")
    )
    print()
    print(
        f"  Hit@1 = {fmt_pct(summary['hit@1'])}    Hit@3 = {fmt_pct(summary['hit@3'])}"
        f"    Hit@5 = {fmt_pct(summary['hit@5'])}    MRR@5 = {fmt_pct(summary['mrr@5'])}"
    )
    refusal = summary["refusal_accuracy"]
    n_refused = counts["refused_expected"]
    if refusal is not None:
        print(f"  拒答正确率 = {refusal:.3f} ({round(refusal * n_refused)}/{n_refused})")
    else:
        print("  拒答正确率 = — （评测集中无 expected_answer_type=refused 的题）")
    print(f"  引用覆盖率 = {fmt_pct(summary['citation_rate'])}")
    print(
        f"  首 token  P50 = {summary['latency_p50_ms']:.0f} ms"
        f"   P95 = {summary['latency_p95_ms']:.0f} ms"
    )
    print()

    if manual:
        thr = 0.85
        ok = manual["accuracy"] >= thr
        print(
            f"  人工判分（已回填）：accuracy = {manual['accuracy']:.3f}  "
            f"({manual['correct']}/{manual['scored']})   阈值 {thr:.2f}  →  "
            f"{'✅ 通过' if ok else '❌ 未通过'}"
        )
        kappa = manual.get("kappa")
        print(
            f"  标注一致性 Cohen's Kappa = "
            f"{'—' if kappa is None else f'{kappa:.3f}'} ({manual['annotators']} 人)"
        )
        et = manual.get("error_types") or {}
        keys = ("retrieval_miss", "incomplete", "hallucination", "citation_wrong", "outdated")
        print("  错误分布：" + "  ".join(f"{k}={et.get(k, 0)}" for k in keys))
    else:
        print("  人工判分（待回填）：accuracy = — (--/--)   阈值 0.85  →  ⏳ 待判分")
        print("    用 --export-answers 导出 answers xlsx，按 §6.2 双人独立判分回填后，再加 --import-scores 汇总")
        print("  标注一致性 Cohen's Kappa = — （待回填，2 人）")
        print("  错误分布：retrieval_miss=—  incomplete=—  hallucination=—  citation_wrong=—  outdated=—")
    print()
    print("================ 与基线对比 ================")
    if baseline:
        bsum = baseline.get("summary", baseline)
        bacc = (bsum.get("manual_accuracy") or {}).get("accuracy") if isinstance(bsum, dict) else None
        b_batch = baseline.get("batch_no", "基线")
        print(
            f"  基线 ({b_batch}): accuracy={fmt_pct(bacc)} "
            f"hit@5={fmt_pct(bsum.get('hit@5') if isinstance(bsum, dict) else None)} "
            f"p95={(bsum.get('latency_p95_ms') if isinstance(bsum, dict) else None) or 0:.0f} ms"
        )
        cur_acc = (manual or {}).get("accuracy")
        print(
            f"  本次 ({summary['batch_no']}): accuracy={fmt_pct(cur_acc)} "
            f"hit@5={fmt_pct(summary['hit@5'])} p95={summary['latency_p95_ms']:.0f} ms"
        )
        if bacc is not None and cur_acc is not None and isinstance(bsum, dict):
            d_acc = cur_acc - bacc
            d_hit = (summary["hit@5"] or 0) - (bsum.get("hit@5") or 0)
            d_p95 = summary["latency_p95_ms"] - (bsum.get("latency_p95_ms") or 0)
            verdict = "→ 变更被采纳" if d_acc >= -0.02 else "→ 准确率下降 > 2 个百分点，按 docs/05 §13 回滚"
            print(f"  Δaccuracy = {d_acc:+.3f}   Δhit@5 = {d_hit:+.3f}   Δp95 = {d_p95:+.0f} ms   {verdict}")
        else:
            print("  （基线或本次缺人工判分结果，仅对比 hit@5 / p95）")
    else:
        print("  未提供基线（--baseline reports/eval_xxx.json），跳过对比")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="eval_rag.py",
        description="RAG 准确率评测脚本（批量问答评测，docs/09 §6.3）：Hit@N / MRR@5 / 拒答正确率 / 引用覆盖率 / 首 token 时延",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python scripts/eval_rag.py --dataset data/eval/eval_set.xlsx \\\n"
            "    --base-url http://localhost:8000/api/v1 --username admin --password Admin@123 \\\n"
            "    --mode hybrid --rerank false --top-k 5 --batch-no EVAL-20250601 \\\n"
            "    --out reports/eval_20250601.json --export-answers reports/answers_20250601.xlsx"
        ),
    )
    parser.add_argument("--dataset", type=Path, required=True, help="评测集 xlsx 路径（docs/09 §6.1）")
    parser.add_argument("--base-url", required=True, help="接口基地址，如 http://localhost:8000/api/v1")
    parser.add_argument("--username", default=None, help="登录用户名（与 --token 二选一）")
    parser.add_argument("--password", default=None, help="登录密码")
    parser.add_argument("--token", default=None, help="直接提供 access_token，跳过登录")
    parser.add_argument(
        "--mode",
        choices=("keyword", "vector", "hybrid"),
        default="hybrid",
        help="检索模式（docs/06 §5.7），默认 hybrid",
    )
    parser.add_argument(
        "--rerank",
        nargs="?",
        const=True,
        default=None,
        type=str2bool,
        help="重排开关，如 --rerank false；不传则由服务端默认配置决定",
    )
    parser.add_argument("--top-k", type=int, default=5, help="问答检索 Top-K（1~10），默认 5")
    parser.add_argument(
        "--retrieve-top-k",
        type=int,
        default=None,
        help="计算 Hit@N 时 /retrieve 的候选条数，默认 max(top-k, 5)",
    )
    parser.add_argument("--kb-ids", default=None, help="限定知识库 id，逗号分隔，如 1,2")
    parser.add_argument("--batch-no", default=None, help="评测批次号，如 EVAL-20250601；缺省自动生成")
    parser.add_argument("--out", type=Path, default=None, help="JSON 报告输出路径，默认 reports/eval_<batch>.json")
    parser.add_argument("--export-answers", type=Path, default=None, help="导出 answers xlsx（人工判分回填用）")
    parser.add_argument("--import-scores", type=Path, default=None, help="读取回填后的 answers xlsx，汇总人工判分")
    parser.add_argument("--baseline", type=Path, default=None, help="历史评测 JSON，用于打印对比报告")
    parser.add_argument("--stream", action="store_true", help="走 /qa/ask/stream（SSE）并统计真实 TTFT")
    parser.add_argument("--no-retrieve", action="store_true", help="跳过 /retrieve 调用（不计算 Hit@N / MRR@5）")
    parser.add_argument("--limit", type=int, default=None, help="只评测前 N 题（调试用）")
    parser.add_argument("--qid", default=None, help="只评测指定题号，逗号分隔，如 Q001,Q007（调试用）")
    parser.add_argument("--delay", type=float, default=0.0, help="每题之间的间隔秒数，默认 0")
    parser.add_argument("--timeout", type=float, default=120.0, help="单请求超时秒数，默认 120")
    args = parser.parse_args(argv)

    if not args.token and (not args.username or not args.password):
        parser.error("必须提供 --username/--password 或 --token 之一")
    if not (1 <= args.top_k <= 10):
        parser.error("--top-k 取值范围为 1~10（docs/06 §5.8 参数校验）")
    if args.retrieve_top_k is None:
        args.retrieve_top_k = max(args.top_k, 5)
    if args.kb_ids:
        try:
            args.kb_ids = [int(x) for x in args.kb_ids.split(",") if x.strip()]
        except ValueError:
            parser.error("--kb-ids 需为逗号分隔的整数，如 1,2")
    else:
        args.kb_ids = None
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        items = load_dataset(args.dataset)
        if args.limit:
            items = items[: args.limit]
        if args.qid:
            wanted = {q.strip() for q in args.qid.split(",") if q.strip()}
            items = [it for it in items if it.qid in wanted]
            if not items:
                raise AppError(f"--qid 未匹配到任何题目：{args.qid}")

        batch_no = args.batch_no or datetime.now().strftime("EVAL-%Y%m%d-%H%M")
        out_path = args.out or Path("reports") / f"eval_{batch_no}.json"

        print(f"开始评测：{len(items)} 题   batch={batch_no}   模式={args.mode}"
              f"   {'SSE 流式' if args.stream else '非流式'}")
        records: list[dict[str, Any]] = []
        with ApiClient(args.base_url, args.username, args.password, args.token, args.timeout) as client:
            client.login()
            for i, item in enumerate(items, 1):
                rec = evaluate_one(client, item, args)
                records.append(rec)
                mark = "❌" if rec.get("error") else ("✅" if rec.get("hit@5") or rec.get("refusal_correct") or rec.get("answer") else "·")
                ttft = rec.get("first_token_ms")
                print(
                    f"[{i}/{len(items)}] {item.qid} {mark} "
                    f"hit@5={rec.get('hit@5')} rr={rec.get('reciprocal_rank')} "
                    f"type={rec.get('answer_type')} ttft={ttft if ttft is not None else '—'} ms"
                    + (f"  ⚠️ {rec['error']}" if rec.get("error") else "")
                )
                if args.delay > 0 and i < len(items):
                    time.sleep(args.delay)

        summary = summarize(records, args, batch_no)
        manual = import_scores(args.import_scores, records) if args.import_scores else None
        if manual:
            summary["manual_accuracy"] = manual

        report = {
            "batch_no": batch_no,
            "generated_at": now_iso(),
            "summary": summary,
            "questions": records,
        }
        baseline = None
        if args.baseline:
            if not args.baseline.exists():
                raise AppError(f"基线文件不存在：{args.baseline}")
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写入：{out_path}")

        if args.export_answers:
            export_answers(args.export_answers, records)
            print(f"答案明细（人工判分回填用）已写入：{args.export_answers}")

        print_report(summary, manual, baseline)
        return 0 if summary["counts"]["failed"] == 0 else 1
    except KeyboardInterrupt:
        print("\n已中断（KeyboardInterrupt）。", file=sys.stderr)
        return 130
    except AppError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
