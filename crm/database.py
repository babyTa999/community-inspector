"""Database configuration for CRM."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

try:
    from crm.models import Base
except ImportError:
    from models import Base

# Database configuration
# Use environment variable DATABASE_URL for PostgreSQL
# Format: postgresql://user:password@host:port/dbname
# Fallback to SQLite for development
DEFAULT_DB_PATH = "crm.db"


SQLITE_CRM_ENTRY_MIGRATIONS = {
    "version": "ALTER TABLE crm_entries ADD COLUMN version INTEGER DEFAULT 1",
    "last_edited_by": "ALTER TABLE crm_entries ADD COLUMN last_edited_by VARCHAR(100)",
    "last_edited_at": "ALTER TABLE crm_entries ADD COLUMN last_edited_at DATETIME",
    "is_being_edited": "ALTER TABLE crm_entries ADD COLUMN is_being_edited BOOLEAN DEFAULT 0",
    "edited_by_session": "ALTER TABLE crm_entries ADD COLUMN edited_by_session VARCHAR(100)",
    "edit_session_expires": "ALTER TABLE crm_entries ADD COLUMN edit_session_expires DATETIME",
}


def get_database_url() -> str:
    """Get database URL from environment or use SQLite default."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Check for PostgreSQL-specific env vars
    pg_host = os.getenv("POSTGRES_HOST")
    if pg_host:
        pg_user = os.getenv("POSTGRES_USER", "crm")
        pg_pass = os.getenv("POSTGRES_PASSWORD", "crm")
        pg_db = os.getenv("POSTGRES_DB", "crm")
        pg_port = os.getenv("POSTGRES_PORT", "5432")
        return f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"

    # Default to SQLite
    return f"sqlite:///{DEFAULT_DB_PATH}"


def get_engine(database_url: str | None = None):
    """Create database engine."""
    url = database_url or get_database_url()

    if url.startswith("sqlite"):
        # SQLite configuration
        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, echo=False)

        # Enable WAL mode for better concurrency
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode = WAL")
            conn.exec_driver_sql("PRAGMA busy_timeout = 5000")
            conn.commit()
    else:
        # PostgreSQL configuration
        engine = create_engine(
            url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # Verify connections before using
        )

    return engine


def get_session_maker(engine):
    """Get session maker bound to engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_sqlite_schema(engine) -> None:
    """Add missing SQLite columns for existing CRM databases."""
    inspector = inspect(engine)
    if "crm_entries" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("crm_entries")}
    statements = [
        statement
        for column_name, statement in SQLITE_CRM_ENTRY_MIGRATIONS.items()
        if column_name not in existing_columns
    ]
    if not statements:
        return

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def init_db(engine):
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        _migrate_sqlite_schema(engine)


# Global engine and session factory
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


def reset_db():
    """Reset global database connection (for testing)."""
    global _engine, _session_maker
    _engine = None
    _session_maker = None
