"""向量化工厂（docs/00 ADR-02：本地 bge / 云 API 可切换，不改业务代码）。

约束：查询向量与写入向量必须同模型、同维度（EMBEDDING_DIM=1024）、同归一化方式。
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Dict, List, Optional, Protocol

from loguru import logger

from app.core.config import settings


class Embedder(Protocol):
    dim: int

    def encode(self, texts: List[str]) -> List[List[float]]:  # pragma: no cover
        ...


class LocalBgeEmbedder:
    """本地 sentence-transformers 推理（bge-large-zh-v1.5 / BGE-M3）。"""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.dim = settings.embedding_dim
        self.model = SentenceTransformer(
            settings.embedding_model,
            device=settings.embedding_device,
            cache_folder=settings.embedding_cache_dir or None,
        )

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=settings.embedding_normalize,
            show_progress_bar=False,
        )
        return [list(map(float, v)) for v in vectors]


class CloudEmbedder:
    """OpenAI 兼容 embedding 接口（如阿里云 text-embedding-v3，1024 维）。"""

    def __init__(self) -> None:
        from openai import OpenAI

        self.dim = settings.embedding_dim
        self.client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        self.model = settings.embedding_model

    def encode(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), settings.embedding_batch_size):
            batch = texts[i : i + settings.embedding_batch_size]
            resp = self.client.embeddings.create(model=self.model, input=batch)
            out.extend([d.embedding for d in resp.data])
        return out


class FakeEmbedder:
    """确定性伪向量（测试/降级用，docs/09 §3.2）：字符 n-gram 哈希 → 相近文本相近向量。"""

    dim = 1024

    def encode(self, texts: List[str]) -> List[List[float]]:
        vecs: List[List[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for i, ch in enumerate(t):
                v[(ord(ch) + i) % self.dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            vecs.append([x / norm for x in v])
        return vecs


_embedder: Optional[Embedder] = None
_lock = threading.Lock()
_query_cache: "OrderedDict[str, List[float]]" = OrderedDict()


def get_embedder() -> Embedder:
    """按 EMBEDDING_PROVIDER 装配（local / cloud / fake）。"""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is None:
            provider = (settings.embedding_provider or "local").lower()
            try:
                if provider == "cloud":
                    _embedder = CloudEmbedder()
                elif provider == "fake":
                    _embedder = FakeEmbedder()
                else:
                    _embedder = LocalBgeEmbedder()
                logger.info("Embedding 装配完成 provider={} model={}", provider, settings.embedding_model)
            except Exception as exc:
                logger.exception("Embedding 模型加载失败，拒绝使用错误向量继续入库: {}", exc)
                raise
    return _embedder


def encode_query(text: str) -> List[float]:
    """查询向量化 + LRU 缓存（docs/05 §10：缓存最近 QUERY_VECTOR_CACHE_SIZE 条）。"""
    key = hashlib.md5(text.encode("utf-8")).hexdigest()
    cached = _query_cache.get(key)
    if cached is not None:
        _query_cache.move_to_end(key)
        return cached
    vector = get_embedder().encode([text])[0]
    _query_cache[key] = vector
    while len(_query_cache) > settings.query_vector_cache_size:
        _query_cache.popitem(last=False)
    return vector


def reset_embedder() -> None:
    """测试用：清空单例与缓存。"""
    global _embedder
    _embedder = None
    _query_cache.clear()
