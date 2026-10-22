"""知识点关联重建（docs/05 §11）：按向量相似度 ≥ 0.75 生成 same_topic 关联。

建议每日离线执行：cd backend && python scripts/build_relations.py
接口优先读 knowledge_point_relation 表，表内无数据时实时计算并回填。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.session import session_scope  # noqa: E402
from app.models.knowledge_point import KnowledgePoint, KnowledgePointRelation  # noqa: E402
from app.rag.embedder import encode_query  # noqa: E402
from app.rag.indexer import build_filter, indexer  # noqa: E402

SIMILARITY_THRESHOLD = 0.75
TOP_N = 5


def main() -> None:
    with session_scope() as db:
        kps = db.scalars(
            select(KnowledgePoint).where(KnowledgePoint.status == "published")
        ).all()
        print(f"[relations] 待处理知识点 {len(kps)} 条")
        created = 0
        for kp in kps:
            vector = encode_query(f"{kp.title}\n{kp.content}")
            rows = indexer.search(
                vector=vector,
                expr=build_filter(categories=[kp.category], source_types=["knowledge_point"]),
                limit=TOP_N * 3,
            )
            kept = 0
            for row in rows:
                target_id = int(row.get("source_id") or 0)
                distance = float(row.get("distance") or 0)
                if target_id == kp.id or distance < SIMILARITY_THRESHOLD:
                    continue
                target = db.get(KnowledgePoint, target_id)
                if target is None or target.primary_document_id == kp.primary_document_id:
                    continue
                exists = db.scalar(
                    select(KnowledgePointRelation).where(
                        KnowledgePointRelation.source_kp_id == kp.id,
                        KnowledgePointRelation.target_kp_id == target_id,
                        KnowledgePointRelation.relation_type == "same_topic",
                    )
                )
                if exists is None:
                    db.add(
                        KnowledgePointRelation(
                            source_kp_id=kp.id,
                            target_kp_id=target_id,
                            relation_type="same_topic",
                            score=round(distance, 4),
                        )
                    )
                    created += 1
                kept += 1
                if kept >= TOP_N:
                    break
        db.commit()
        print(f"[relations] 完成，新增关联 {created} 条")


if __name__ == "__main__":
    main()
