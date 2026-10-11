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
