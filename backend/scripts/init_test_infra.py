"""Initialize isolated integration infrastructure (never drops data)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.models import Base
from app.db.session import get_engine
from app.db.init_milvus import init_collection
from sqlalchemy import inspect, text

assert all(name.startswith('finrag_test_') for name in (
    settings.mysql_database, settings.milvus_collection, settings.milvus_alias))
engine = get_engine()
Base.metadata.create_all(engine)
with engine.begin() as connection:
    for table, name, fields in (
        ('document_chunk', 'ft_chunk_content', 'content'),
        ('knowledge_point', 'ft_kp_content', 'title, content, keywords')):
        names = {index['name'] for index in inspect(connection).get_indexes(table)}
        if name not in names:
            connection.execute(text(f'ALTER TABLE {table} ADD FULLTEXT INDEX {name} ({fields}) WITH PARSER ngram'))
init_collection()
print('Isolated integration infrastructure initialized')
