"""Read-only SQL/vector ID audit; connection failures are errors, not zero."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.db.session import session_scope
from app.db.init_milvus import get_collection
from app.models.chunk import DocumentChunk
from app.models.knowledge_point import KnowledgePoint, KnowledgePointSource

collection = get_collection()
collection.load()
with session_scope() as db:
    report = {}
    for kind, model in [('chunk', DocumentChunk), ('knowledge_point', KnowledgePoint)]:
        sql_ids = set(db.scalars(select(model.id)).all())
        vector_ids = {row['source_id'] for row in collection.query(
            expr=f'source_type == "{kind}"', output_fields=['source_id'])}
        report[kind] = {'sql':len(sql_ids), 'vectors':len(vector_ids),
            'missing_vectors':sorted(sql_ids-vector_ids), 'orphan_vectors':sorted(vector_ids-sql_ids)}
    sources = db.scalars(select(KnowledgePointSource)).all()
    report['broken_sources'] = [s.id for s in sources if db.get(KnowledgePoint,s.knowledge_point_id) is None
        or db.get(DocumentChunk,s.chunk_id) is None]
print(json.dumps(report, indent=2))
if report['broken_sources'] or any(report[k]['missing_vectors'] or report[k]['orphan_vectors']
    for k in ('chunk','knowledge_point')):
    raise SystemExit(1)
