"""数据库连接与 Session 管理（SQLAlchemy 2.0 + PyMySQL）。"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.sqlalchemy_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=settings.db_echo,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求一个 Session，异常回滚。"""
    db: Session = get_session_factory()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """脚本/后台任务用：事务作用域，退出即提交或回滚。"""
    db = get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ping() -> float:
    """健康检查用：执行 SELECT 1 并返回毫秒延迟。"""
    import time

    start = time.perf_counter()
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return (time.perf_counter() - start) * 1000
