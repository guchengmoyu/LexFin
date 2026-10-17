"""问答服务（QaService）：docs/05 §1 在线问答链的业务编排。

链路：查询理解 →（多轮改写）→ 混合检索 → 拒答判定 → Prompt 组装 →
LLM 流式生成（SSE）→ 溯源解析 + 可信度评分 → 落库。
SSE 事件序列见 docs/06 §5.8：meta（检索完成立即下发）→ token* → done。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import AnswerType, ErrorCode
from app.core.exceptions import BizError
from app.models.favorite import Favorite
from app.models.feedback import QAFeedback
from app.models.knowledge_point import KnowledgePoint
from app.models.qa import QACitation, QAMessage, QASession
from app.models.user import User
from app.rag import citation as citation_mod
from app.rag import llm as llm_factory  # 运行期解析 get_llm，便于测试注入 FakeLLM
from app.rag import scorer
from app.rag.prompt import (
    PROMPT_VERSION,
    build_messages,
    build_refusal_answer,
)
from app.rag.query_rewriter import analyze, need_rewrite, rewrite
from app.rag.retriever.hybrid_retriever import hybrid_retriever
from app.rag.retriever.reranker import rerank
from app.rag.types import Citation, RetrievedItem
from app.utils.time import gen_no, now


class QaService:
    # ================================================================ 对外
    async def ask(self, db: Session, user: User, payload: dict) -> dict:
        """非流式问答（docs/06 §5.8）：内部复用事件流，收集后一次性返回。"""
        events: List[Tuple[str, dict]] = []
        async for event in self.ask_stream(db, user, payload):
            events.append(event)
        meta = next((d for e, d in events if e == "meta"), {})
        done = next((d for e, d in events if e == "done"), {})
        error = next((d for e, d in events if e == "error"), {})
        answer_parts = [d.get("delta", "") for e, d in events if e == "token"]
        if error:
            raise BizError(error.get("code", ErrorCode.LLM_ERROR), error.get("message", "生成失败"))
        message = db.get(QAMessage, meta.get("message_id")) if meta.get("message_id") else None
        # 落库内容为最终答案（拒答/替换场景与流式中间态可能不同），以落库为准
        final_answer = message.content if message is not None and message.content else "".join(answer_parts)
        # citations 仅包含答案实际引用的条目（docs/06 §5.8）；refused 时为 []
        used_indexes = set(done.get("used_citations") or [])
        all_citations = meta.get("citations", [])
        citations = (
            [c for c in all_citations if c.get("cite_index") in used_indexes]
            if "used_citations" in done
            else all_citations
        )
        result = {
            "message_id": meta.get("message_id"),
            "session_no": meta.get("session_no"),
            "question": payload["question"],
            "answer": final_answer,
            "answer_type": done.get("answer_type", "answered"),
            "retrieval_mode": payload.get("mode") or "hybrid",
            "confidence": done.get("confidence", 0.0),
            "confidence_level": done.get("confidence_level", "low"),
            "latency_ms": done.get("latency_ms"),
            "latency_detail": done.get("latency_detail"),
            "model_name": done.get("model_name"),
            "prompt_version": PROMPT_VERSION,
            "token_usage": done.get("token_usage"),
            "citations": citations,
            "related": done.get("related", []),
            "suggestions": done.get("suggestions", []),
        }
        return result

    async def ask_stream(
        self, db: Session, user: User, payload: dict
    ) -> AsyncIterator[Tuple[str, dict]]:
        """SSE 事件流：(event_name, data)。客户端断开也会把已生成内容落库。"""
        t0 = time.perf_counter()
        latency = {"rewrite": 0, "retrieve": 0, "rerank": 0, "llm_ttft": 0, "total": 0}

        session = self._get_or_create_session(db, user, payload)
        question = payload["question"].strip()

        # 落库 user 消息
        user_msg = QAMessage(
            session_id=session.id,
            user_id=user.id,
            role="user",
            content=question,
            kb_id=session.kb_id,
            created_at=now(),
        )
        db.add(user_msg)
        session.message_count += 1
        session.last_active_at = now()
        db.commit()

        # ① 查询理解 + ② 多轮改写（P1）
        t_rewrite = time.perf_counter()
        query_info = analyze(question)
        history = self._history(db, session.id, user.id, payload.get("use_history", True))
        if need_rewrite(question, bool(history)):
            llm = llm_factory.get_llm()
            rewritten = await rewrite(question, history, llm)
            query_info.rewritten = rewritten
        latency["rewrite"] = int((time.perf_counter() - t_rewrite) * 1000)

        # ③ 检索（向量 + 关键词并行 + RRF + 去重）
        t_retrieve = time.perf_counter()
        try:
            items = await hybrid_retriever.retrieve(
                db,
                query_info,
                mode=payload.get("mode") or "hybrid",
                kb_ids=payload.get("kb_ids"),
                categories=payload.get("categories"),
                timeliness=payload.get("timeliness"),
                top_k=payload.get("top_k") or settings.final_top_n,
            )
        except BizError as exc:
            yield ("error", {"code": exc.code, "message": exc.message})
            return
        latency["retrieve"] = int((time.perf_counter() - t_retrieve) * 1000)

        # ④ 重排（一期为按分截断）
        t_rerank = time.perf_counter()
        items = rerank(query_info.effective_query, items, payload.get("top_k") or settings.final_top_n)
        latency["rerank"] = int((time.perf_counter() - t_rerank) * 1000)

        # ⑤ 拒答判定（前置，docs/05 §5）
        citations = citation_mod.build_citations(items)
        refused_reason = self._pre_refuse(items, question)
        answer_text = ""
        answer_type = AnswerType.answered.value
        token_usage: dict = {}
        model_name = ""

        if refused_reason is not None:
            answer_type = AnswerType.refused.value
            answer_text = refused_reason
            citations_used: List[Citation] = []
        else:
            # ⑥ Prompt 组装 + ⑦ LLM 流式生成
            messages = build_messages(query_info.effective_query, items)
            llm = llm_factory.get_llm()
            model_name = getattr(llm, "model_name", settings.llm_model)
            assistant_msg_id = self._save_assistant_placeholder(db, session, user, user_msg, payload)

            # meta 事件：检索完成立即下发引用列表（docs/05 §8.1）
            yield (
                "meta",
                {
                    "message_id": assistant_msg_id,
                    "session_no": session.session_no,
                    "citations": [c.to_dict() for c in citations],
                    "answer_type_pending": True,
                },
            )

            chunks: List[str] = []
            try:
                async for delta in llm.astream(messages):
                    if not delta:
                        continue
                    if not chunks:
                        latency["llm_ttft"] = int((time.perf_counter() - t0) * 1000)
                    chunks.append(delta)
                    yield ("token", {"delta": delta})
            except asyncio.CancelledError:
                # 客户端断开：取消 LLM 请求，但已生成内容仍落库（docs/06 §5.8 规则 4）
                self._finalize(
                    db, assistant_msg_id, "".join(chunks) or "（用户中断生成）",
                    AnswerType.error.value, payload, latency, [], None, {}, model_name, t0,
                )
                raise
            except BizError as exc:
                # 备用渠道也失败：返回 error + 检索证据列表（docs/05 §7）
                answer_text = "".join(chunks)
                yield ("error", {"code": exc.code, "message": exc.message})
                self._finalize(
                    db, assistant_msg_id, answer_text or "（生成失败）",
                    AnswerType.error.value, payload, latency, [], None, {}, model_name, t0,
                )
                return
            answer_text = "".join(chunks)
            token_usage = getattr(llm, "last_usage", {}) or {}

            # ⑧ 溯源解析 + 后置拒答判定（docs/05 §5 后置规则）
            citations_used = citation_mod.resolve(answer_text, citations)
            final_answer = answer_text
            if not citations_used or self._is_refusal_text(answer_text):
                answer_type = AnswerType.refused.value
                # 丢弃 LLM 生成内容，改用标准拒答话术（若尚未流出文本则直接下发模板）
                final_answer = build_refusal_answer(
                    question, query_info.cleaned, query_info.keywords
                )
                if not answer_text:
                    answer_text = final_answer
                    yield ("token", {"delta": answer_text})
                citations_used = []
            confidence = scorer.score(
                answer_text, citations, [c.score for c in citations], citations_used
            )
            latency["total"] = int((time.perf_counter() - t0) * 1000)
            self._finalize(
                db, assistant_msg_id, final_answer, answer_type, payload,
                latency, citations_used, confidence, token_usage, model_name, t0,
            )
            yield (
                "done",
                {
                    "answer_type": answer_type,
                    "confidence": confidence,
                    "confidence_level": scorer.level(confidence),
                    "latency_ms": latency["total"],
                    "latency_detail": dict(latency),
                    "token_usage": token_usage,
                    "used_citations": [c.cite_index for c in citations_used],
                    "suggestions": self._suggestions(db, items),
                    "model_name": model_name,
                },
            )
            return

        # 拒答路径：不调用 LLM，直接落库 + 返回
        assistant_msg_id = self._save_assistant_placeholder(db, session, user, user_msg, payload)
        yield (
            "meta",
            {
                "message_id": assistant_msg_id,
                "session_no": session.session_no,
                "citations": [c.to_dict() for c in citations],
                "answer_type_pending": True,
            },
        )
        yield ("token", {"delta": answer_text})
        confidence = 0.0
        latency["total"] = int((time.perf_counter() - t0) * 1000)
        self._finalize(
            db, assistant_msg_id, answer_text, answer_type, payload,
            latency, [], confidence, {}, "", t0,
        )
        yield (
            "done",
            {
                "answer_type": answer_type,
                "confidence": confidence,
                "confidence_level": scorer.level(confidence),
                "latency_ms": latency["total"],
                "latency_detail": dict(latency),
                "token_usage": {},
                "used_citations": [],
                "suggestions": [],
                "model_name": "",
            },
        )

    # ================================================================ 会话
    def list_sessions(self, db: Session, user: User, page: int, size: int) -> dict:
        from app.core.response import paged

        total = db.scalar(
            select(func.count()).select_from(QASession).where(QASession.user_id == user.id)
        ) or 0
        rows = db.scalars(
            select(QASession)
            .where(QASession.user_id == user.id)
            .order_by(QASession.last_active_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
        items = [
            {
                "session_no": s.session_no,
                "title": s.title,
                "kb_id": s.kb_id,
                "message_count": s.message_count,
                "last_active_at": s.last_active_at.strftime("%Y-%m-%d %H:%M:%S")
                if s.last_active_at
                else None,
            }
            for s in rows
        ]
        return paged(total, page, size, items)

    def session_detail(self, db: Session, user: User, session_no: str) -> dict:
        session = self._get_session(db, user, session_no)
        messages = db.scalars(
            select(QAMessage)
            .where(QAMessage.session_id == session.id)
            .order_by(QAMessage.id)
        ).all()
        out_messages = []
        for m in messages:
            item = {
                "message_id": m.id,
                "role": m.role,
                "content": m.content,
                "answer_type": m.answer_type,
                "confidence": float(m.confidence) if m.confidence is not None else None,
                "latency_ms": m.latency_ms,
                "created_at": m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else None,
            }
            if m.role == "assistant":
                item["citations"] = self._citations_of(db, m.id)
                item["favorited"] = (
                    db.scalar(
                        select(func.count())
                        .select_from(Favorite)
                        .where(Favorite.user_id == user.id, Favorite.message_id == m.id)
                    )
                    or 0
                ) > 0
                fb = db.scalar(
                    select(QAFeedback).where(
                        QAFeedback.user_id == user.id, QAFeedback.message_id == m.id
                    )
                )
                item["feedback"] = (
                    {"rating": fb.rating, "reason": fb.reason, "comment": fb.comment}
                    if fb
                    else None
                )
            out_messages.append(item)
        return {
            "session_no": session.session_no,
            "title": session.title,
            "kb_id": session.kb_id,
            "created_at": session.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if session.created_at
            else None,
            "messages": out_messages,
        }

    def delete_session(self, db: Session, user: User, session_no: str) -> dict:
        session = self._get_session(db, user, session_no)
        db.query(QAMessage).filter(QAMessage.session_id == session.id).delete()
        db.delete(session)
        db.commit()
        return {"session_no": session_no, "deleted": True}

    def message_detail(self, db: Session, user: User, message_id: int) -> dict:
        message = db.get(QAMessage, message_id)
        if message is None or message.user_id != user.id:
            raise BizError(ErrorCode.NOT_FOUND, "消息不存在")
        return {
            "message_id": message.id,
            "session_id": message.session_id,
            "role": message.role,
            "content": message.content,
            "answer_type": message.answer_type,
            "retrieval_mode": message.retrieval_mode,
            "confidence": float(message.confidence) if message.confidence is not None else None,
            "latency_ms": message.latency_ms,
            "latency_detail": message.latency_detail,
            "prompt_version": message.prompt_version,
            "model_name": message.model_name,
            "token_usage": message.token_usage,
            "citations": self._citations_of(db, message.id),
            "created_at": message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if message.created_at
            else None,
        }

    # ================================================================ 内部
    def _get_or_create_session(self, db: Session, user: User, payload: dict) -> QASession:
        session_no = payload.get("session_no")
        if session_no:
            session = db.scalar(select(QASession).where(QASession.session_no == session_no))
            if session is None:
                raise BizError(ErrorCode.SESSION_NOT_FOUND, "会话不存在")
            if session.user_id != user.id:
                raise BizError(ErrorCode.FORBIDDEN, "无操作权限")
            return session
        kb_ids = payload.get("kb_ids")
        session = QASession(
            session_no=gen_no("s"),
            user_id=user.id,
            title=payload["question"][:50],
            kb_id=kb_ids[0] if kb_ids else None,
            message_count=0,
            last_active_at=now(),
            created_at=now(),
            updated_at=now(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def _get_session(self, db: Session, user: User, session_no: str) -> QASession:
        session = db.scalar(select(QASession).where(QASession.session_no == session_no))
        if session is None:
            raise BizError(ErrorCode.SESSION_NOT_FOUND, "会话不存在")
        if session.user_id != user.id:
            raise BizError(ErrorCode.FORBIDDEN, "无操作权限")
        return session

    @staticmethod
    def _history(
        db: Session, session_id: int, user_id: int, use_history: bool
    ) -> List[Tuple[str, str]]:
        """最近 N 轮（question, answer 摘要），供多轮改写（docs/05 §2.3）。"""
        if not use_history or not settings.multi_turn_enabled:
            return []
        rows = db.scalars(
            select(QAMessage)
            .where(QAMessage.session_id == session_id)
            .order_by(QAMessage.id.desc())
            .limit(settings.multi_turn_history_size * 2)
        ).all()
        rows = list(reversed(rows))
        history: List[Tuple[str, str]] = []
        i = 0
        while i < len(rows) - 1:
            if rows[i].role == "user" and rows[i + 1].role == "assistant":
                history.append((rows[i].content, rows[i + 1].content[:120]))
                i += 2
            else:
                i += 1
        return history[-settings.multi_turn_history_size :]

    @staticmethod
    def _pre_refuse(items: Sequence[RetrievedItem], question: str) -> Optional[str]:
        """前置拒答（docs/05 §5）：无结果或 Top-1 融合分低于阈值。

        注（ADR-10）：RRF 融合分为 1/(K+rank) 量纲（经验值约 0.01~0.05，
        故 docs/05 §9 以 RRF_REF=0.03 作归一化基准）；RETRIEVAL_MIN_SCORE=0.30
        因此按 `top1 / RRF_REF` 归一化后与阈值比较，而非与原始 RRF 分直接比较。
        """
        if not items:
            return build_refusal_answer(question)
        # Optional calibrated gate for vector-only evidence. Keyword/structured
        # evidence keeps its separate contract; no uncalibrated default cutoff.
        threshold = settings.qa_min_vector_similarity
        if threshold > 0 and not any(item.keyword_rank is not None for item in items):
            similarities = [item.vector_similarity for item in items if item.vector_similarity is not None]
            if not similarities or max(similarities) < threshold:
                return build_refusal_answer(question)
        normalized_top1 = items[0].score / (settings.rrf_ref or 0.03)
        if normalized_top1 < settings.retrieval_min_score:
            return build_refusal_answer(question)
        return None

    @staticmethod
    def _is_refusal_text(text: str) -> bool:
        markers = ("暂未检索到", "未检索到相关规定", "无法回答", "根据现有知识库，暂未检索到")
        return any(m in (text or "") for m in markers)

    def _save_assistant_placeholder(
        self, db: Session, session: QASession, user: User, user_msg: QAMessage, payload: dict
    ) -> int:
        """检索完成后立即占位落库（meta 事件需要 message_id）。"""
        message = QAMessage(
            session_id=session.id,
            user_id=user.id,
            parent_id=user_msg.id,
            role="assistant",
            content="",
            answer_type=None,
            retrieval_mode=payload.get("mode") or "hybrid",
            prompt_version=PROMPT_VERSION,
            kb_id=session.kb_id,
            created_at=now(),
        )
        db.add(message)
        session.message_count += 1
        db.commit()
        db.refresh(message)
        return int(message.id)

    def _finalize(
        self,
        db: Session,
        message_id: int,
        answer_text: str,
        answer_type: str,
        payload: dict,
        latency: dict,
        used_citations: Sequence[Citation],
        confidence: Optional[float],
        token_usage: dict,
        model_name: str,
        t0: float,
    ) -> None:
        """落库 assistant 消息 + 引用（含客户端断开场景）。"""
        message = db.get(QAMessage, message_id)
        if message is None:
            return
        message.content = answer_text or ""
        message.answer_type = answer_type
        message.confidence = confidence
        message.latency_ms = int((time.perf_counter() - t0) * 1000)
        message.latency_detail = dict(latency)
        message.model_name = model_name or None
        message.token_usage = dict(token_usage) if token_usage else None
        for c in used_citations:
            db.add(
                QACitation(
                    message_id=message_id,
                    cite_index=c.cite_index,
                    chunk_id=c.chunk_id,
                    knowledge_point_id=c.knowledge_point_id,
                    document_id=c.document_id,
                    doc_title=(c.doc_title or "")[:300] or None,
                    doc_no=(c.doc_no or "")[:100] or None,
                    issuing_authority=(c.issuing_authority or "")[:100] or None,
                    article_no=(c.article_no or "")[:50] or None,
                    page_no=c.page_no,
                    timeliness=c.timeliness,
                    snippet=(c.snippet or "")[:1000],
                    score=c.score,
                    created_at=now(),
                )
            )
        session = db.get(QASession, message.session_id)
        if session is not None:
            session.last_active_at = now()
        db.commit()

    @staticmethod
    def _citations_of(db: Session, message_id: int) -> List[dict]:
        rows = db.scalars(
            select(QACitation)
            .where(QACitation.message_id == message_id)
            .order_by(QACitation.cite_index)
        ).all()
        return [
            {
                "cite_index": c.cite_index,
                "chunk_id": c.chunk_id,
                "knowledge_point_id": c.knowledge_point_id,
                "document_id": c.document_id,
                "doc_title": c.doc_title,
                "doc_no": c.doc_no,
                "issuing_authority": c.issuing_authority,
                "article_no": c.article_no,
                "page_no": c.page_no,
                "timeliness": c.timeliness,
                "snippet": c.snippet,
                "score": float(c.score) if c.score is not None else None,
                "source_url": f"/api/v1/documents/{c.document_id}/download#page={c.page_no}"
                if c.document_id
                else None,
            }
            for c in rows
        ]

    @staticmethod
    def _suggestions(db: Session, items: Sequence[RetrievedItem]) -> List[str]:
        """推荐追问：取同主题知识点标题，最多 3 条（docs/06 §5.8）。"""
        categories = list({i.category for i in items if i.category})
        if not categories:
            return []
        rows = db.scalars(
            select(KnowledgePoint.title)
            .where(
                KnowledgePoint.category.in_(categories),
                KnowledgePoint.status == "published",
            )
            .order_by(KnowledgePoint.id)
            .limit(8)
        ).all()
        used_titles = {i.title for i in items if i.title}
        suggestions = [t for t in rows if t not in used_titles][:3]
        return suggestions


qa_service = QaService()
