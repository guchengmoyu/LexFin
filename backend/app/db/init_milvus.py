"""Milvus 集合初始化（docs/03 §3）。

集合名 finrag_embedding_v1，别名 finrag_embedding —— 代码只使用别名，
便于零停机重建索引（docs/03 §3.5）。
"""
from __future__ import annotations

from typing import List, Optional

from loguru import logger

from app.core.config import settings

# pymilvus 为重量级依赖，延迟导入（保证 app.rag 纯算法可独立导入与测试）


def connect(alias: str = "default") -> None:
    from pymilvus import connections

    connections.connect(
        alias=alias,
        host=settings.milvus_host,
        port=str(settings.milvus_port),
        timeout=settings.milvus_timeout,
    )


def get_collection(name: Optional[str] = None, alias: str = "default"):
    """代码统一通过别名拿集合。"""
    from pymilvus import Collection

    connect(alias)
    return Collection(name or settings.milvus_alias, using=alias)


def build_schema():
    from pymilvus import CollectionSchema, DataType, FieldSchema

    fields = [
        FieldSchema("pk", DataType.VARCHAR, is_primary=True, max_length=64, auto_id=False),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=settings.embedding_dim),
        FieldSchema("source_type", DataType.VARCHAR, max_length=16),
        FieldSchema("source_id", DataType.INT64),
        FieldSchema("kb_id", DataType.INT64),
        FieldSchema("document_id", DataType.INT64),
        FieldSchema("category", DataType.VARCHAR, max_length=32),
        FieldSchema("timeliness", DataType.VARCHAR, max_length=16),
        FieldSchema("article_no", DataType.VARCHAR, max_length=32),
        FieldSchema("page_no", DataType.INT32),
        FieldSchema("chunk_index", DataType.INT32),
        FieldSchema("publish_year", DataType.INT32),
        FieldSchema("content", DataType.VARCHAR, max_length=8192),
    ]
    return CollectionSchema(fields=fields, description="FinRAG 切片+知识点向量（docs/03 §3.2）")


def init_collection(drop: bool = False):
    """创建集合 + 向量索引 + 标量索引 + 别名（幂等）。"""
    from pymilvus import Collection, utility

    connect()
    name = settings.milvus_collection
    if utility.has_collection(name):
        if drop:
            utility.drop_collection(name)
        else:
            col = Collection(name)
            _ensure_alias(col)
            return col

    col = Collection(name=name, schema=build_schema())
    col.create_index(
        field_name="embedding",
        index_params={
            "index_type": settings.milvus_index_type,
            "metric_type": settings.milvus_metric_type,
            "params": {
                "M": settings.milvus_hnsw_m,
                "efConstruction": settings.milvus_hnsw_ef_construction,
            },
        },
    )
    for field in ("kb_id", "source_type", "category"):
        try:
            col.create_index(field_name=field, index_params={"index_type": "INVERTED"})
        except Exception as exc:  # 老版本 Milvus 可能不支持标量索引
            logger.warning("创建标量索引 {} 失败（可忽略）: {}", field, exc)
    _ensure_alias(col)
    logger.info("Milvus 集合 {} 初始化完成，别名 {}", name, settings.milvus_alias)
    return col


def _ensure_alias(col) -> None:
    from pymilvus import utility

    try:
        if settings.milvus_alias not in utility.list_aliases(col.name):
            utility.create_alias(collection_name=col.name, alias=settings.milvus_alias)
    except Exception as exc:
        logger.warning("创建别名失败（可能已存在）: {}", exc)


def init_milvus() -> None:
    try:
        init_collection()
    except Exception as exc:  # Milvus 不可用时不阻断后端启动，/health 会报 degraded
        logger.error("Milvus 初始化失败: {}", exc)
