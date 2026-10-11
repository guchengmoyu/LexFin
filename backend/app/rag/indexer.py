"""Milvus 读写封装（docs/03 §3.4 写入与删除约定）。

重要：document_chunk.id 为 MySQL 自增主键，入库流程必须
「先写 MySQL 拿到 id → 再写 Milvus」，保证 Milvus 失败可重放。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.exceptions import BizError
from app.db.init_milvus import get_collection
from app.rag.types import RetrievedItem

OUTPUT_FIELDS = [
    "source_type", "source_id", "kb_id", "document_id", "category", "timeliness",
    "article_no", "page_no", "chunk_index", "content", "publish_year",
]


class VectorIndexer:
    """Milvus 集合管理、批量 upsert/delete、向量检索。"""

    def _collection(self):
        try:
            return get_collection()
        except Exception as exc:
            raise BizError(ErrorCode.VECTOR_ERROR, "向量库连接失败，请稍后重试") from exc

    # ------------------------------------------------------------------ 写入
    def upsert(self, rows: List[Dict[str, Any]]) -> int:
        """rows 为 docs/03 §3.2 schema 字段字典列表，pk 形如 chunk_{id} / kp_{id}。"""
        if not rows:
            return 0
        try:
            col = self._collection()
            col.upsert(
                data=[
                    [r["pk"] for r in rows],
                    [r["embedding"] for r in rows],
                    [r["source_type"] for r in rows],
                    [r["source_id"] for r in rows],
                    [r["kb_id"] for r in rows],
                    [r["document_id"] for r in rows],
                    [r.get("category", "") for r in rows],
                    [r.get("timeliness", "unknown") for r in rows],
                    [r.get("article_no") or "" for r in rows],
                    [int(r.get("page_no") or 0) for r in rows],
                    [int(r.get("chunk_index") or -1) for r in rows],
                    [int(r.get("publish_year") or 0) for r in rows],
                    [(r.get("content") or "")[:8000] for r in rows],
                ]
            )
            col.flush()
            return len(rows)
        except BizError:
            raise
        except Exception as exc:
            logger.exception("Milvus upsert 失败")
            raise BizError(ErrorCode.VECTOR_ERROR, "向量库写入失败，请稍后重试") from exc

    # ------------------------------------------------------------------ 删除
    def delete_by_document(self, document_id: int) -> int:
        return self._delete(f"document_id == {int(document_id)}")

    def delete_kp(self, kp_id: int) -> int:
        return self._delete(f'pk == "kp_{int(kp_id)}"')

    def delete_by_kb(self, kb_id: int) -> int:
        return self._delete(f"kb_id == {int(kb_id)}")

    def _delete(self, expr: str) -> int:
        try:
            col = self._collection()
            col.delete(expr)
            col.flush()
            return 0
        except Exception as exc:
            logger.exception("Milvus delete 失败 expr={}", expr)
            raise BizError(ErrorCode.VECTOR_ERROR, "向量库删除失败，请稍后重试") from exc

    # ------------------------------------------------------------------ 检索
    def search(
        self,
        vector: List[float],
        expr: str,
        limit: int,
        output_fields: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            col = self._collection()
            col.load()
            results = col.search(
                data=[vector],
                anns_field="embedding",
                param={
                    "metric_type": settings.milvus_metric_type,
                    "params": {"ef": settings.milvus_search_ef},
                },
                limit=limit,
                expr=expr or None,
                output_fields=list(output_fields or OUTPUT_FIELDS),
            )
            out: List[Dict[str, Any]] = []
            for hit in results[0]:
                row = {field: hit.entity.get(field) for field in (output_fields or OUTPUT_FIELDS)}
                row["distance"] = float(hit.distance)
                row["pk"] = hit.id
                out.append(row)
            return out
        except Exception as exc:
            logger.exception("Milvus 检索失败")
            raise BizError(ErrorCode.VECTOR_ERROR, "向量检索失败，请稍后重试") from exc

    # ------------------------------------------------------------------ 统计
    def count(self, expr: str = "") -> int:
        try:
            col = self._collection()
            col.load()
            return len(col.query(expr=expr or 'pk != ""', output_fields=["pk"]))
        except Exception as exc:
            logger.warning("Milvus count 失败: {}", exc)
            return 0

    def entities(self, expr: str = "") -> List[Dict[str, Any]]:
        try:
            col = self._collection()
            col.load()
            return col.query(expr=expr or 'pk != ""', output_fields=list(OUTPUT_FIELDS))
        except Exception as exc:
            logger.warning("Milvus query 失败: {}", exc)
            return []


# --------------------------------------------------------------------------- #
#  过滤表达式（docs/05 §3.1 build_filter）
# --------------------------------------------------------------------------- #
def build_filter(
    kb_ids: Optional[Sequence[int]] = None,
    categories: Optional[Sequence[str]] = None,
    timeliness: Optional[Sequence[str]] = None,
    source_types: Optional[Sequence[str]] = None,
) -> str:
    parts: List[str] = []
    if kb_ids:
        parts.append(f"kb_id in [{','.join(str(int(k)) for k in kb_ids)}]")
    if categories:
        parts.append("category in [" + ",".join(f'"{c}"' for c in categories) + "]")
    if timeliness:
        parts.append("timeliness in [" + ",".join(f'"{t}"' for t in timeliness) + "]")
    st = list(source_types or ["chunk", "knowledge_point"])
    parts.append("source_type in [" + ",".join(f'"{s}"' for s in st) + "]")
    return " and ".join(parts)


def row_to_item(row: Dict[str, Any]) -> RetrievedItem:
    """Milvus 行 → RetrievedItem（content 冗余免回表 MySQL，docs/03 §3.2）。"""
    source_type = row.get("source_type", "chunk")
    return RetrievedItem(
        source_type=source_type,
        source_id=int(row.get("source_id") or 0),
        kb_id=int(row.get("kb_id") or 0),
        document_id=int(row.get("document_id") or 0),
        category=row.get("category") or "",
        timeliness=row.get("timeliness") or "unknown",
        article_no=row.get("article_no") or None,
        page_no=int(row.get("page_no") or 0) or None,
        chunk_index=int(row.get("chunk_index") or -1),
        content=row.get("content") or "",
        raw_content=(row.get("content") or "").split("\n", 1)[-1],
        vector_similarity=float(row["distance"]) if row.get("distance") is not None else None,
    )


indexer = VectorIndexer()
