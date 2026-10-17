"""Read-only BGE relevance probe against ready banking document chunks."""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.db.session import get_session_factory
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.rag.embedder import get_embedder, LocalBgeEmbedder

queries = ['商业银行流动性覆盖率的最低要求是多少？',
           '流动性风险压力测试有哪些要求？',
           '请问明天双色球的中奖号码是多少？',
           '如何制作蛋糕？', '北京明天会下雨吗？']
with get_session_factory()() as db:
    chunks = db.scalars(select(DocumentChunk).join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.status == 'ready', Document.category == 'banking')).all()
    assert chunks, 'Ready banking chunks required'
    embedder = get_embedder()
    assert isinstance(embedder, LocalBgeEmbedder), 'Real BGE required; fake fallback is not an evaluation'
    vectors = embedder.encode([c.content for c in chunks] + queries)
    report = []
    for query, vector in zip(queries, vectors[len(chunks):]):
        scores = [sum(a*b for a,b in zip(vector, other)) for other in vectors[:len(chunks)]]
        index = max(range(len(scores)), key=scores.__getitem__)
        report.append(dict(query=query, top_similarity=round(scores[index], 4),
                           chunk_id=chunks[index].id, article_no=chunks[index].article_no))
    output = Path(__file__).resolve().parents[3] / 'LexFin/data/runtime/semantic_relevance_probe.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))
