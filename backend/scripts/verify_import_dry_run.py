"""Exercise import validation against finrag without writing SQL or vectors."""
import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func
from app.db.session import session_scope
from app.models.knowledge_point import KnowledgePoint, KnowledgePointSource
from app.models.user import User
from app.services.knowledge_point import knowledge_point_service as service

runtime = Path(__file__).resolve().parents[3] / 'LexFin/data/runtime'
rows = list(csv.DictReader((runtime / 'member2_10kp_trial.csv').open(encoding='utf-8-sig')))


def payload(items):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(items[0]))
    writer.writeheader()
    writer.writerows(items)
    return stream.getvalue().encode('utf-8-sig')


with session_scope() as db:
    user = db.scalar(select(User).where(User.username == 'member2_local'))
    existing = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == rows[0]['code']))
    assert user and existing, 'Run the ten-row trial first'
    before = [db.scalar(select(func.count()).select_from(model))
              for model in (KnowledgePoint, KnowledgePointSource)]
    report = []
    cases = [('existing_valid', [dict(rows[0])], 1, None),
             ('duplicate_code', [dict(rows[0]), dict(rows[0])], 1, 'code')]
    for name, change in [
        ('wrong_page', {'page_no': '999999'}),
        ('invalid_page', {'page_no': 'bad'}),
        ('missing_file', {'source_file': 'missing-validation-file.pdf'}),
        ('missing_quote', {'quote_text': ''}),
        ('unmatched_quote', {'quote_text': 'THIS_QUOTE_DOES_NOT_EXIST_20261011'}),
        ('wrong_category', {'category': 'insurance'}),
    ]:
        row = dict(rows[0]); row.update(change)
        expected_field = 'sub_category' if name == 'wrong_category' else 'source'
        cases.append((name, [row], 0, expected_field))
    for name, items, valid, field in cases:
        result = service.import_file(db, user, existing.kb_id, 'validation.csv', payload(items), True)
        assert result['valid_rows'] == valid, (name, result)
        if field:
            assert any(error['field'] == field for error in result['errors']), (name, result)
        report.append({'case': name, 'passed': True, 'result': result})
    after = [db.scalar(select(func.count()).select_from(model))
             for model in (KnowledgePoint, KnowledgePointSource)]
    assert before == after, 'Dry run changed row counts'
    db.rollback()
result = {'cases': report, 'sql_counts_before': before, 'sql_counts_after': after}
(runtime / 'import_dry_run_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(report), 'sql_counts_before': before, 'sql_counts_after': after}))
