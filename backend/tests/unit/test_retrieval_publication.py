from types import SimpleNamespace
from app.rag.retriever.hybrid_retriever import HybridRetriever
from app.rag.types import RetrievedItem
from app.models.chunk import DocumentChunk


class DB:
    def __init__(self, approved): self.approved = approved
    def scalars(self, query):
        return SimpleNamespace(all=lambda: self.approved)
    def get(self, model, pk):
        if model is DocumentChunk:
            return SimpleNamespace(page_start=7)
        return SimpleNamespace(id=1, title='制度原文', doc_no='文号', issuing_authority='监管机构', status='ready')


def item(kind, source_id):
    return RetrievedItem(source_type=kind, source_id=source_id, kb_id=1, document_id=1, content='原文')


def test_unapproved_vector_is_filtered_without_dropping_chunk():
    chunk = item('chunk', 2)
    assert HybridRetriever._published_items(DB([]), [item('knowledge_point', 1), chunk]) == [chunk]


def test_published_verified_point_gets_source_metadata():
    kp = SimpleNamespace(id=1, title='已审核知识点', content='制度事实', primary_chunk_id=2,
        primary_document_id=1, doc_no=None, issuing_authority=None, article_no='第一条')
    result = HybridRetriever._published_items(DB([kp]), [item('knowledge_point',1)])
    assert len(result) == 1
    assert result[0].page_no == 7
    assert result[0].doc_title == '制度原文'
