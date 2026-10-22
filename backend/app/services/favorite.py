"""收藏与反馈服务（docs/06 §5.10/§5.11）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.core.response import paged as paged_result
from app.models.favorite import Favorite
from app.models.feedback import QAFeedback
from app.models.qa import QAMessage
from app.models.task import QAReview
from app.models.user import User
from app.utils.time import now


class FavoriteService:
    def add(self, db: Session, user: User, message_id: int, note: Optional[str]) -> dict:
        message = db.get(QAMessage, message_id)
        if message is None or message.role != "assistant":
            raise BizError(ErrorCode.NOT_FOUND, "消息不存在")
        fav = db.scalar(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.message_id == message_id)
        )
        if fav is not None:
            fav.note = note  # 重复收藏幂等（覆盖备注）
            db.commit()
            return self._to_dict(fav)
        fav = Favorite(
            user_id=user.id,
            message_id=message_id,
            session_id=message.session_id,
            question=self._question_of(db, message),
            answer_digest=(message.content or "")[:200],
            note=note,
            created_at=now(),
        )
        db.add(fav)
        db.commit()
        db.refresh(fav)
        return self._to_dict(fav)

    def list(self, db: Session, user: User, page: int, size: int) -> dict:
        total = db.scalar(
            select(func.count()).select_from(Favorite).where(Favorite.user_id == user.id)
        )
        rows = db.scalars(
            select(Favorite)
            .where(Favorite.user_id == user.id)
            .order_by(Favorite.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
        items = []
        for fav in rows:
            item = self._to_dict(fav)
            session = db.get(QAMessage, fav.message_id)
            item["session_no"] = self._session_no(db, fav.session_id)
            items.append(item)
        return paged_result(total or 0, page, size, items)

    def update_note(self, db: Session, user: User, message_id: int, note: Optional[str]) -> dict:
        fav = db.scalar(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.message_id == message_id)
        )
        if fav is None:
            raise BizError(ErrorCode.NOT_FOUND, "收藏不存在")
        fav.note = note
        db.commit()
        return self._to_dict(fav)

    def remove(self, db: Session, user: User, message_id: int) -> dict:
        fav = db.scalar(
            select(Favorite).where(Favorite.user_id == user.id, Favorite.message_id == message_id)
        )
        if fav is None:
            raise BizError(ErrorCode.NOT_FOUND, "收藏不存在")
        db.delete(fav)
        db.commit()
        return {"message_id": message_id, "deleted": True}

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _question_of(db: Session, assistant_msg: QAMessage) -> Optional[str]:
        if assistant_msg.parent_id:
            user_msg = db.get(QAMessage, assistant_msg.parent_id)
            return user_msg.content[:500] if user_msg else None
        return None

    @staticmethod
    def _session_no(db: Session, session_id: Optional[int]) -> Optional[str]:
        if not session_id:
            return None
        from app.models.qa import QASession

        s = db.get(QASession, session_id)
        return s.session_no if s else None

    @staticmethod
    def _to_dict(fav: Favorite) -> dict:
        return {
            "message_id": fav.message_id,
            "session_id": fav.session_id,
            "question": fav.question,
            "answer_digest": fav.answer_digest,
            "note": fav.note,
            "created_at": fav.created_at.strftime("%Y-%m-%d %H:%M:%S") if fav.created_at else None,
        }


class FeedbackService:
    def submit(self, db: Session, user: User, message_id: int, payload: dict) -> dict:
        message = db.get(QAMessage, message_id)
        if message is None:
            raise BizError(ErrorCode.NOT_FOUND, "消息不存在")
        feedback = db.scalar(
            select(QAFeedback).where(
                QAFeedback.user_id == user.id, QAFeedback.message_id == message_id
            )
        )
        if feedback is not None:
            feedback.rating = payload["rating"]  # 同一用户同一答案重复提交时覆盖
            feedback.reason = payload.get("reason")
            feedback.comment = payload.get("comment")
            feedback.status = "open"
            feedback.updated_at = now()
        else:
            feedback = QAFeedback(
                message_id=message_id,
                user_id=user.id,
                rating=payload["rating"],
                reason=payload.get("reason"),
                comment=payload.get("comment"),
                status="open",
                created_at=now(),
                updated_at=now(),
            )
            db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return {
            "message_id": feedback.message_id,
            "rating": feedback.rating,
            "status": feedback.status,
            "created_at": feedback.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def list(self, db: Session, filters: dict, page: int, size: int) -> dict:
        query = select(QAFeedback)
        if filters.get("status"):
            query = query.where(QAFeedback.status == filters["status"])
        if filters.get("rating") is not None:
            query = query.where(QAFeedback.rating == filters["rating"])
        if filters.get("reason"):
            query = query.where(QAFeedback.reason == filters["reason"])
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(
            query.order_by(QAFeedback.created_at.desc()).offset((page - 1) * size).limit(size)
        ).all()
        items = []
        for f in rows:
            message = db.get(QAMessage, f.message_id)
            items.append(
                {
                    "id": f.id,
                    "message_id": f.message_id,
                    "user_id": f.user_id,
                    "rating": f.rating,
                    "reason": f.reason,
                    "comment": f.comment,
                    "status": f.status,
                    "answer_digest": (message.content[:200] if message else None),
                    "created_at": f.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return paged_result(total or 0, page, size, items)


class ReviewService:
    """人工校验（★ 85% 准确率的落库入口，docs/06 §5.11）。"""

    def submit(self, db: Session, reviewer: User, payload: dict) -> dict:
        review = db.scalar(
            select(QAReview).where(
                QAReview.reviewer_id == reviewer.id,
                QAReview.target_type == payload["target_type"],
                QAReview.target_id == payload["target_id"],
            )
        )
        if review is not None:
            review.is_correct = payload["is_correct"]
            review.error_type = payload.get("error_type")
            review.comment = payload.get("comment")
            review.batch_no = payload.get("batch_no")
        else:
            review = QAReview(
                target_type=payload["target_type"],
                target_id=payload["target_id"],
                reviewer_id=reviewer.id,
                is_correct=payload["is_correct"],
                error_type=payload.get("error_type"),
                comment=payload.get("comment"),
                batch_no=payload.get("batch_no"),
                created_at=now(),
            )
            db.add(review)
        db.commit()
        db.refresh(review)
        return {
            "review_id": review.id,
            "target_type": review.target_type,
            "target_id": review.target_id,
            "is_correct": review.is_correct,
            "batch_no": review.batch_no,
            "created_at": review.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def stats(self, db: Session, batch_no: str, target_type: str = "answer") -> dict:
        """验收统计：accuracy 直接对照 ≥0.85 阈值输出 pass 字段（docs/06 §5.11）。"""
        base = select(QAReview).where(
            QAReview.batch_no == batch_no, QAReview.target_type == target_type
        )
        total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
        correct = db.scalar(
            select(func.count())
            .select_from(QAReview)
            .where(
                QAReview.batch_no == batch_no,
                QAReview.target_type == target_type,
                QAReview.is_correct == 1,
            )
        ) or 0
        accuracy = round(correct / total, 4) if total else 0.0

        error_rows = db.execute(
            select(QAReview.error_type, func.count())
            .where(
                QAReview.batch_no == batch_no,
                QAReview.target_type == target_type,
                QAReview.is_correct == 0,
            )
            .group_by(QAReview.error_type)
        ).all()
        reviewer_count = db.scalar(
            select(func.count(func.distinct(QAReview.reviewer_id)))
            .where(QAReview.batch_no == batch_no, QAReview.target_type == target_type)
        ) or 0

        return {
            "batch_no": batch_no,
            "target_type": target_type,
            "total": int(total),
            "correct": int(correct),
            "incorrect": int(total - correct),
            "accuracy": accuracy,
            "pass": accuracy >= 0.85,
            "threshold": 0.85,
            "reviewer_count": int(reviewer_count),
            "cohen_kappa": self._cohen_kappa(db, batch_no, target_type),
            "error_type_distribution": [
                {"error_type": r[0] or "unknown", "count": int(r[1])} for r in error_rows
            ],
        }

    @staticmethod
    def _cohen_kappa(db: Session, batch_no: str, target_type: str) -> Optional[float]:
        """双人标注一致性（docs/06 §5.11；≥0.8 高度一致）。"""
        from itertools import combinations

        rows = db.execute(
            select(QAReview.reviewer_id, QAReview.target_id, QAReview.is_correct)
            .where(QAReview.batch_no == batch_no, QAReview.target_type == target_type)
            .order_by(QAReview.reviewer_id, QAReview.target_id)
        ).all()
        by_reviewer: dict[int, dict[int, int]] = {}
        for reviewer_id, target_id, is_correct in rows:
            by_reviewer.setdefault(int(reviewer_id), {})[int(target_id)] = int(is_correct)
        reviewers = list(by_reviewer)
        if len(reviewers) < 2:
            return None
        # 取第一对标注人计算（>2 人时取前两人的平均可后续扩展）
        a, b = reviewers[0], reviewers[1]
        common = set(by_reviewer[a]) & set(by_reviewer[b])
        if not common:
            return None
        n = len(common)
        agree = sum(1 for t in common if by_reviewer[a][t] == by_reviewer[b][t])
        po = agree / n
        pa1 = sum(by_reviewer[a][t] for t in common) / n
        pb1 = sum(by_reviewer[b][t] for t in common) / n
        pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
        if pe == 1.0:
            return 1.0
        return round((po - pe) / (1 - pe), 3)


favorite_service = FavoriteService()
feedback_service = FeedbackService()
review_service = ReviewService()
