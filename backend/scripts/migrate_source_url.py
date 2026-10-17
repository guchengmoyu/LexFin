"""Add provenance URL to the configured finrag database, idempotently."""
from sqlalchemy import inspect, text
from app.db.session import get_engine

engine = get_engine()
with engine.begin() as connection:
    if connection.execute(text('SELECT DATABASE()')).scalar() != 'finrag':
        raise RuntimeError('This local migration only targets finrag')
    columns = {column['name'] for column in inspect(connection).get_columns('knowledge_point_source')}
    if 'source_url' not in columns:
        connection.execute(text('ALTER TABLE knowledge_point_source ADD COLUMN source_url VARCHAR(2000) NULL'))
print('Source URL migration complete')
