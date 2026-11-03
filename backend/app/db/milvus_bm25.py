"""Milvus 2.5 原生 BM25 全文索引（docs/05 §3.2.1）。

背景：通道 B 原先用 MySQL ngram FULLTEXT，NATURAL LANGUAGE MODE 是 OR 语义，
口语泛词的 IDF 会把结果带偏；Milvus 2.5 支持在集合里声明 text 字段 + BM25 Function，
由服务端用 chinese(jieba) 分词建稀疏倒排索引，检索时直接传入原始查询串。

设计要点：
- 与向量集合**分开**存放（finrag_bm25_v1），互不影响，便于单独建/删/重建；
- 只存检索所需的标量字段与正文，命中后直接构造 RetrievedItem，不再回查 MySQL；
- 全部能力由 settings 开关控制（docs/05 §3.2.1 的排列组合实验）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from loguru import logger

from app.core.config import settings

_client: Any = None

TEXT_MAX_LEN = 8192

#: 需要回填到 RetrievedItem 的输出字段
OUTPUT_FIELDS = [
    "pk",
    "source_type",
    "source_id",
    "kb_id",
    "document_id",
    "category",
    "timeliness",
    "article_no",
    "page_no",
    "chunk_index",
    "publish_year",
    "doc_title",
    "doc_no",
    "issuing_authority",
    "content",
]


def uri() -> str:
    return f"http://{settings.milvus_host}:{settings.milvus_port}"


def get_client():
    """延迟创建 MilvusClient（pymilvus 为重量级依赖）。"""
    global _client
    if _client is None:
        from pymilvus import MilvusClient

        _client = MilvusClient(uri=uri(), timeout=settings.milvus_timeout)
    return _client


def reset_client() -> None:
    global _client
    _client = None


def collection_name() -> str:
    return settings.bm25_collection


def has_collection() -> bool:
    return bool(get_client().has_collection(collection_name()))


def init_collection(drop: bool = False) -> None:
    """创建 BM25 集合：text 字段带 chinese analyzer，sparse 字段由 BM25 Function 生成。"""
    from pymilvus import DataType, Function, FunctionType

    client = get_client()
    name = collection_name()
    if client.has_collection(name):
        if not drop:
            return
        client.drop_collection(name)
        logger.info("已删除旧 BM25 集合 {}", name)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("pk", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("source_type", DataType.VARCHAR, max_length=16)
    schema.add_field("source_id", DataType.INT64)
    schema.add_field("kb_id", DataType.INT64)
    schema.add_field("document_id", DataType.INT64, nullable=True)
    schema.add_field("category", DataType.VARCHAR, max_length=64, nullable=True)
    schema.add_field("timeliness", DataType.VARCHAR, max_length=16, nullable=True)
    schema.add_field("article_no", DataType.VARCHAR, max_length=64, nullable=True)
    schema.add_field("page_no", DataType.INT32, nullable=True)
    schema.add_field("chunk_index", DataType.INT32, nullable=True)
    schema.add_field("publish_year", DataType.INT32, nullable=True)
    schema.add_field("doc_title", DataType.VARCHAR, max_length=512, nullable=True)
    schema.add_field("doc_no", DataType.VARCHAR, max_length=256, nullable=True)
    schema.add_field("issuing_authority", DataType.VARCHAR, max_length=128, nullable=True)
    schema.add_field("content", DataType.VARCHAR, max_length=TEXT_MAX_LEN)
    schema.add_field(
        "text",
        DataType.VARCHAR,
        max_length=TEXT_MAX_LEN,
        enable_analyzer=True,
        analyzer_params={"type": settings.bm25_analyzer},
    )
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="bm25_text",
            function_type=FunctionType.BM25,
            input_field_names=["text"],
            output_field_names=["sparse"],
        )
    )

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
    )
    for field in ("kb_id", "source_type", "document_id"):
        index_params.add_index(field_name=field, index_type="INVERTED")
    client.create_collection(collection_name=name, schema=schema, index_params=index_params)
    logger.info(
        "BM25 集合 {} 初始化完成（analyzer={}）", name, settings.bm25_analyzer
    )


def upsert_rows(rows: Sequence[Dict[str, Any]], batch_size: int = 100) -> int:
    """批量写入/覆盖（pk 与向量集合一致：chunk_{id} / kp_{id}）。"""
    if not rows:
        return 0
    client = get_client()
    name = collection_name()
    written = 0
    batch: List[Dict[str, Any]] = []
    for row in rows:
        item = {k: v for k, v in row.items() if v is not None}
        item["content"] = (item.get("content") or "")[:TEXT_MAX_LEN]
        item["text"] = (item.get("text") or item.get("content") or "")[:TEXT_MAX_LEN]
        batch.append(item)
        if len(batch) >= batch_size:
            client.upsert(collection_name=name, data=batch)
            written += len(batch)
            batch = []
    if batch:
        client.upsert(collection_name=name, data=batch)
        written += len(batch)
    return written


def delete(expr: str) -> None:
    get_client().delete(collection_name=collection_name(), filter=expr)


def count() -> int:
    rows = get_client().query(
        collection_name=collection_name(), filter="", output_fields=["count(*)"]
    )
    return int(rows[0]["count(*)"]) if rows else 0


def query(
    expr: str,
    limit: int = 20,
    output_fields: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """按标量条件精确取行（条号/文号线索命中用，不走 BM25 排序）。"""
    rows = get_client().query(
        collection_name=collection_name(),
        filter=expr,
        limit=limit,
        output_fields=list(output_fields or OUTPUT_FIELDS),
    )
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        item = dict(row)
        item["_score"] = 0.0
        out.append(item)
    return out


def search(
    text: str,
    limit: int,
    expr: Optional[str] = None,
    output_fields: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """原文检索：data 直接传查询串，服务端用集合的 analyzer 分词后走 BM25。"""
    client = get_client()
    res = client.search(
        collection_name=collection_name(),
        data=[text],
        anns_field="sparse",
        search_params={"metric_type": "BM25"},
        limit=limit,
        filter=expr or None,
        output_fields=list(output_fields or OUTPUT_FIELDS),
    )
    # MilvusClient.search 返回 [ [ {id, distance, entity} ... ] ]
    hits: List[Dict[str, Any]] = []
    for group in res or []:
        for hit in group:
            entity = dict(hit.get("entity") or {})
            entity.setdefault("pk", hit.get("id"))
            entity["_score"] = float(hit.get("distance") or 0.0)
            hits.append(entity)
    return hits
