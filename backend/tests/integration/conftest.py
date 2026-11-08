"""集成测试夹具（docs/09 §4.1）。

需要真实 MySQL + Milvus（docker-compose.infra.yml 启动）；
LLM 与 Embedding 用确定性 Fake 实现。
基础设施未就绪时自动 skip，不报错。
"""
from __future__ import annotations

import hashlib
import os
from typing import AsyncIterator, Generator, List

import pytest
from httpx import ASGITransport, AsyncClient

# --------------------------------------------------------------------------- #
#  确定性 Fake（docs/09 §3.2）
# --------------------------------------------------------------------------- #
class FakeEmbedder:
    dim = 1024

    def encode(self, texts: List[str]) -> List[List[float]]:
        vecs = []
        for t in texts:
            v = [0.0] * self.dim
            for i, ch in enumerate(t or ""):
                v[(ord(ch) + i) % self.dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            vecs.append([x / norm for x in v])
        return vecs


class FakeLLM:
    def __init__(self, answer: str | None = None) -> None:
        self.answer = answer or "商业银行的流动性覆盖率应当不低于100%[1]。"
        self.model_name = "fake-llm"
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}

    async def astream(self, messages, **kw):
        for ch in self.answer:
            yield ch

    async def ainvoke(self, messages, **kw) -> str:
        return self.answer


# --------------------------------------------------------------------------- #
#  基础设施探测
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session", autouse=True)
def ensure_infra() -> None:
    from app.core.config import settings
    if os.environ.get("LEXFIN_INTEGRATION") != "1":
        pytest.skip("Set LEXFIN_INTEGRATION=1 with isolated test infrastructure")
    if not (settings.mysql_database.startswith("finrag_test_")
            and settings.milvus_collection.startswith("finrag_test_")
            and settings.milvus_alias.startswith("finrag_test_")):
        pytest.fail("Integration tests require finrag_test_ database, collection and alias; refusing shared data")
    from app.db.session import ping

    try:
        ping()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"需要 MySQL 就绪（docker compose -f docker-compose.infra.yml up -d）：{exc}")


@pytest.fixture()
def fake_embedder(monkeypatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    monkeypatch.setattr("app.rag.embedder.get_embedder", lambda: fake)
    monkeypatch.setattr("app.rag.embedder.encode_query", lambda t: fake.encode([t])[0])
    return fake


@pytest.fixture()
def fake_llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr("app.rag.llm.get_llm", lambda **kw: fake)
    return fake


# --------------------------------------------------------------------------- #
#  数据库：每用例一个事务，结束回滚（docs/09 §3.2）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db_session() -> Generator:
    from app.db.session import get_engine
    from sqlalchemy.orm import sessionmaker

    engine = get_engine()
    conn = engine.connect()
    tx = conn.begin()
    Session = sessionmaker(bind=conn, autoflush=False, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    tx.rollback()
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def sample_corpus(ensure_infra):
    """Persist one deterministic sample in isolated infrastructure only."""
    from sqlalchemy import select
    from app.db.session import session_scope
    from app.db.seed import seed_all
    from app.models.knowledge_base import KnowledgeBase
    from app.models.document import Document
    from app.models.chunk import DocumentChunk
    from app.models.knowledge_point import KnowledgePoint
    from app.rag.indexer import indexer
    from app.db.init_milvus import get_collection

    body = "第三十八条 流动性覆盖率的最低监管标准为不低于100%。"
    with session_scope() as db:
        seed_all(db)
        kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.category == "banking"))
        digest = hashlib.md5(body.encode()).hexdigest()
        doc = db.scalar(select(Document).where(Document.kb_id == kb.id, Document.file_md5 == digest))
        if doc is None:
            doc = Document(kb_id=kb.id, title="集成测试样本（非正式制度）", category="banking",
                           file_name="integration_sample.txt", file_path="integration_sample.txt",
                           file_ext="txt", file_md5=digest, status="ready", timeliness="effective",
                           page_count=1, chunk_count=1)
            db.add(doc); db.flush()
        chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        if chunk is None:
            chunk = DocumentChunk(document_id=doc.id, kb_id=kb.id, chunk_index=0,
                                  article_no="第三十八条", page_start=1, page_end=1,
                                  content=body, raw_content=body, embedding_status=1)
            db.add(chunk); db.flush()
        indexer.upsert([dict(pk=f"chunk_{chunk.id}", embedding=FakeEmbedder().encode([body])[0],
                            source_type="chunk", source_id=chunk.id, kb_id=kb.id,
                            document_id=doc.id, category="banking", timeliness="effective",
                            article_no="第三十八条", page_no=1, chunk_index=0, content=body)])
        kp = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == "IT-KP-0001"))
        if kp is None:
            kp = KnowledgePoint(kb_id=kb.id, code="IT-KP-0001",
                                title="流动性覆盖率最低监管标准是什么？", content=body,
                                category="banking", sub_category="流动性风险", article_no="第三十八条",
                                timeliness="effective", status="published", verify_status="passed",
                                primary_document_id=doc.id, primary_chunk_id=chunk.id,
                                embedding_status=1)
            db.add(kp); db.flush()
        indexer.upsert([dict(pk=f"kp_{kp.id}", embedding=FakeEmbedder().encode([kp.title + "\n" + kp.content])[0],
                            source_type="knowledge_point", source_id=kp.id, kb_id=kb.id,
                            document_id=doc.id, category="banking", timeliness="effective",
                            article_no="第三十八条", page_no=1, chunk_index=-1,
                            content=kp.title + "\n" + kp.content)])
    # Integration failure must be visible, never interpreted as an empty corpus.
    col = get_collection(); col.load()
    assert col.query(expr=f'pk == "chunk_{chunk.id}"', output_fields=["source_id"])


# --------------------------------------------------------------------------- #
#  API 客户端
# --------------------------------------------------------------------------- #
@pytest.fixture()
async def client(db_session, fake_embedder, fake_llm) -> AsyncIterator[AsyncClient]:
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
async def auth_client(client: AsyncClient, db_session) -> AsyncClient:
    """以种子管理员登录；服务端 seed 由启动钩子创建（集成环境需先起过后端一次）。"""
    from app.db.seed import seed_all

    seed_all(db_session)
    db_session.commit()
    r = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "Admin@123"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client
