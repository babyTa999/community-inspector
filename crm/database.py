"""Database configuration for CRM."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from crm.models import Base

DEFAULT_DB_PATH = "/data/crm.db"


def get_db_path() -> str:
    """Get database path from environment or default."""
    return os.getenv("CRM_DB_PATH", DEFAULT_DB_PATH)


def get_engine(db_path: str | None = None):
    """Create database engine."""
    path = db_path or get_db_path()
    # Ensure directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def get_session_maker(engine):
    """Get session maker bound to engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(engine):
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    # Enable WAL mode
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode = WAL")
        conn.exec_driver_sql("PRAGMA busy_timeout = 5000")
        conn.commit()


# Global engine and session factory (initialized on first use)
_engine = None
_session_maker = None


def get_db():
    """Get database session (for dependency injection)."""
    global _engine, _session_maker
    if _engine is None:
        _engine = get_engine()
        init_db(_engine)
        _session_maker = get_session_maker(_engine)

    db = _session_maker()
    try:
        yield db
    finally:
        db.close()
