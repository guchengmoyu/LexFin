from app.rag.indexer import row_to_item
from app.rag.retriever.hybrid_retriever import rrf_fuse
from app.services.qa import QaService
from app.core.config import settings


def test_raw_similarity_survives_fusion(make_item):
    vector = make_item(vector_rank=1, vector_similarity=0.24)
    keyword = make_item(keyword_rank=2)
    result = rrf_fuse([vector], [keyword])[0]
    assert result.vector_similarity == 0.24
    assert result.vector_rank == 1 and result.keyword_rank == 2
    assert row_to_item({'distance': 0.0}).vector_similarity == 0.0


def test_optional_gate_rejects_low_similarity_but_not_keyword_evidence(make_item, monkeypatch):
    monkeypatch.setattr(settings, 'qa_min_vector_similarity', 0.4)
    weak = make_item(score=0.02, vector_similarity=0.24, vector_rank=1)
    assert QaService._pre_refuse([weak], 'test question') is not None
    strong = make_item(score=0.02, vector_similarity=0.7, vector_rank=1)
    assert QaService._pre_refuse([strong], 'test question') is None
    weak.keyword_rank = 1
    assert QaService._pre_refuse([weak], 'test question') is None


def test_default_gate_keeps_existing_behavior(make_item, monkeypatch):
    monkeypatch.setattr(settings, 'qa_min_vector_similarity', 0.0)
    assert QaService._pre_refuse([make_item(score=0.02)], 'test question') is None
