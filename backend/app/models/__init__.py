"""ORM 模型汇总（映射 deploy/mysql/init/01-schema.sql，字段名与 docs/03 一致）。"""
from app.db.base import Base  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.knowledge_base import KnowledgeBase  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.chunk import DocumentChunk  # noqa: F401
from app.models.knowledge_point import (  # noqa: F401
    KnowledgePoint,
    KnowledgePointRelation,
    KnowledgePointSource,
)
from app.models.qa import QACitation, QAMessage, QASession  # noqa: F401
from app.models.favorite import Favorite  # noqa: F401
from app.models.feedback import QAFeedback  # noqa: F401
from app.models.task import IngestTask, QAReview  # noqa: F401
from app.models.system_config import SystemConfig  # noqa: F401
from app.models.operation_log import OperationLog  # noqa: F401

__all__ = [
    "Base",
    "User",
    "KnowledgeBase",
    "Document",
    "DocumentChunk",
    "KnowledgePoint",
    "KnowledgePointSource",
    "KnowledgePointRelation",
    "QASession",
    "QAMessage",
    "QACitation",
    "Favorite",
    "QAFeedback",
    "QAReview",
    "IngestTask",
    "SystemConfig",
    "OperationLog",
]
