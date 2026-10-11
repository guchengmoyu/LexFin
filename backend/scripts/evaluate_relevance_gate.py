"""Exploratory gate evaluation with provisional liquidity-corpus labels."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.rag.embedder import get_embedder, LocalBgeEmbedder
from app.rag.indexer import indexer
from app.core.config import settings
from app.db.session import get_session_factory
from app.models.chunk import DocumentChunk
from app.models.document import Document
from sqlalchemy import select
assert settings.embedding_normalize and settings.milvus_metric_type == "COSINE"
positive = ["流动性覆盖率最低要求是多少？", "流动性风险压力测试有哪些要求？", "如何管理日间流动性风险？", "董事会承担哪些流动性风险管理职责？", "如何制定流动性应急计划？", "流动性风险限额如何管理？", "净稳定资金比例最低标准是什么？", "银行应披露哪些流动性风险信息？", "融资渠道集中度如何管理？", "监管机构如何检查流动性风险？"]
negative = ["明天双色球中奖号码是多少？", "如何制作蛋糕？", "北京明天会下雨吗？", "Python如何读取Excel？", "写一首关于春天的诗。", "证券法如何处罚内幕交易？", "保险销售有哪些告知义务？", "商业银行资本充足率最低要求是什么？", "存款保险最高偿付限额是多少？", "个人住房贷款利率现在是多少？"]
embedder = get_embedder()
assert isinstance(embedder, LocalBgeEmbedder), "Real BGE required"
records = []
for question, vector in zip(positive + negative, embedder.encode(positive + negative)):
    hits = indexer.search(vector, 'kb_id == 1 and source_type == "chunk"', 1)
    assert hits, "Expected banking corpus"
    records.append(dict(question=question, provisional_answerable=question in positive, similarity=hits[0]["distance"], chunk_id=hits[0]["source_id"], article_no=hits[0]["article_no"]))
metrics = []
for threshold in [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]:
    metrics.append(dict(threshold=threshold, false_accept=sum(not r["provisional_answerable"] and r["similarity"] >= threshold for r in records), false_reject=sum(r["provisional_answerable"] and r["similarity"] < threshold for r in records)))
with get_session_factory()() as db:
    for record in records:
        chunk = db.get(DocumentChunk, record["chunk_id"])
        assert chunk is not None, "Vector references missing SQL chunk"
        doc = db.get(Document, chunk.document_id)
        assert doc is not None and doc.status == "ready"
        record.update(document_id=doc.id, document_title=doc.title,
                      page_start=chunk.page_start, page_end=chunk.page_end,
                      retrieved_quote=chunk.raw_content, label_review_status="pending")
output = Path(__file__).resolve().parents[3] / "LexFin/data/runtime/relevance_gate_evaluation.json"
output.write_text(json.dumps(dict(model=settings.embedding_model, metric=settings.milvus_metric_type, records=records, thresholds=metrics, note="Provisional labels; liquidity-only corpus; not QA accuracy"), ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(metrics))
