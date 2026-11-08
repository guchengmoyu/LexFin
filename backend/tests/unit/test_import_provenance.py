from types import SimpleNamespace
import pytest
from app.services.knowledge_point import KnowledgePointService


class Results:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class SourceDB:
    def __init__(self, chunks, documents=None):
        self.results = iter([documents if documents is not None else [SimpleNamespace(id=1)], chunks])
    def scalars(self, query): return Results(next(self.results))


def test_unique_quote_and_page_bind_to_chunk():
    chunk = SimpleNamespace(raw_content='第一条 应当不低于１００％。', page_start=2, page_end=3)
    row = {'source_file':'source.pdf', 'quote_text':'应当不低于100%。', 'page_no':'3'}
    assert KnowledgePointService()._resolve_import_source(SourceDB([chunk]), 1, row) is chunk


@pytest.mark.parametrize('page', ['1', '4', 'bad'])
def test_wrong_page_is_rejected(page):
    chunk = SimpleNamespace(raw_content='制度事实', page_start=2, page_end=3)
    with pytest.raises(ValueError):
        KnowledgePointService()._resolve_import_source(SourceDB([chunk]), 1,
            {'source_file':'source.pdf', 'quote_text':'制度事实', 'page_no':page})


def test_ambiguous_quote_is_not_guessed():
    chunk = SimpleNamespace(raw_content='制度事实', page_start=2, page_end=3)
    with pytest.raises(ValueError):
        KnowledgePointService()._resolve_import_source(SourceDB([chunk, chunk]), 1,
            {'source_file':'source.pdf', 'quote_text':'制度事实'})


def test_missing_document_is_rejected():
    with pytest.raises(ValueError):
        KnowledgePointService()._resolve_import_source(SourceDB([], documents=[]), 1,
            {'source_file':'missing.pdf', 'quote_text':'制度事实'})


@pytest.mark.parametrize('field,value', [
    ('effective_date', '2018-99-01'),
    ('expiry_date', 'yesterday'),
    ('timeliness', 'current'),
    ('difficulty', '0'),
    ('difficulty', '4'),
])
def test_import_metadata_format_is_rejected(field, value):
    row = {'title': 'Valid metadata title', 'content': 'This is a sufficiently long policy fact content.',
           'category': 'banking', field: value}
    error = KnowledgePointService()._validate_import_row(row)
    assert error is not None and error[0] == field


def test_published_requires_passed_review():
    row = {'title': 'Valid metadata title', 'content': 'This is a sufficiently long policy fact content.',
           'category': 'banking', 'status': 'published', 'verify_status': 'pending'}
    assert KnowledgePointService()._validate_import_row(row)[0] == 'status'


def test_insurance_law_review_category_is_accepted():
    row = {'title': '保险合同与监管要求是什么？', 'content': '保险合同与监管内容足够完整，可以独立阅读。',
           'category': 'insurance', 'sub_category': '保险合同与监管'}
    assert KnowledgePointService()._validate_import_row(row) is None


def test_model_load_failure_does_not_fall_back_to_incompatible_vectors(monkeypatch):
    from app.core.config import settings
    from app.rag import embedder

    def fail_to_load():
        raise RuntimeError("model cache unavailable")

    embedder.reset_embedder()
    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(embedder, "LocalBgeEmbedder", fail_to_load)
    with pytest.raises(RuntimeError, match="model cache unavailable"):
        embedder.get_embedder()
    embedder.reset_embedder()


def test_long_chinese_article_range_is_omitted_from_milvus_scalar():
    from app.rag.indexer import _article_no_for_milvus

    assert _article_no_for_milvus("第三十八条") == "第三十八条"
    assert _article_no_for_milvus("第一百零一条~第一百零二条") == ""


def test_excel_native_dates_are_normalized():
    import io
    from datetime import datetime
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['title', 'content', 'category', 'effective_date', 'expiry_date'])
    sheet.append(['Valid policy title', 'A sufficiently long policy fact.', 'banking',
                  datetime(2018, 7, 1), None])
    stream = io.BytesIO()
    workbook.save(stream)
    row = KnowledgePointService._parse_import_file('dates.xlsx', stream.getvalue())[0]
    assert row['effective_date'] == '2018-07-01'
    assert row['expiry_date'] == ''
    assert KnowledgePointService._validate_import_row(row) is None
