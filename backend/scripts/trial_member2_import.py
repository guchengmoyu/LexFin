"""Local ten-row trial; strict unique quote matching, not a full importer."""
import csv
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy import select
from app.db.session import session_scope
from app.models.knowledge_point import KnowledgePoint, KnowledgePointSource
from app.models.chunk import DocumentChunk
from app.models.user import User
from app.services.knowledge_point import knowledge_point_service as svc
from app.rag.embedder import get_embedder, LocalBgeEmbedder

root = Path(__file__).resolve().parents[3] / 'LexFin/data/runtime'
rows = list(csv.DictReader((root / 'member2_10kp_trial.csv').open(encoding='utf-8-sig')))
normalize = lambda s: re.sub(r'\s+', '', unicodedata.normalize('NFKC', s or ''))
assert isinstance(get_embedder(), LocalBgeEmbedder), 'Real BGE required'
report = []
with session_scope() as db:
    user = db.scalar(select(User).where(User.username == 'member2_local'))
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == 1)).all()
    for row in rows:
        quote = normalize(row['quote_text'])
        matches = [c for c in chunks if quote and quote in normalize(c.raw_content)]
        svc._upsert_import_row(db, user, chunks[0].kb_id, row)
        kp = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == row['code']))
        if len(matches) == 1:
            chunk = matches[0]
            source = db.scalar(select(KnowledgePointSource).where(
                KnowledgePointSource.knowledge_point_id == kp.id,
                KnowledgePointSource.chunk_id == chunk.id))
            page = int(row['page_no'])
            assert chunk.page_start <= page <= chunk.page_end
            if source is None:
                db.add(KnowledgePointSource(knowledge_point_id=kp.id, chunk_id=chunk.id,
                    document_id=1, page_no=page, article_no=row['article_no'],
                    quote_text=row['quote_text'], is_primary=1))
            kp.primary_chunk_id = chunk.id
            kp.primary_document_id = 1
            svc._index_kp(kp)
        report.append({'code':kp.code, 'id':kp.id, 'verify_status':kp.verify_status,
            'status':kp.status, 'source_matches':len(matches), 'chunk_id':kp.primary_chunk_id})
(root / 'member2_10kp_sources.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True))
