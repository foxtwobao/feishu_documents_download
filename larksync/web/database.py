"""SQLAlchemy database configuration for LarkSync Web."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

logger = logging.getLogger(__name__)

# SQLAlchemy declarative base
Base = declarative_base()

# Module-level engine and session factory
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def configure_database(database_url: str) -> Engine:
    """
    Configure the database engine.
    
    Args:
        database_url: SQLAlchemy database URL (e.g., sqlite:///./larksync.db)
        
    Returns:
        Configured SQLAlchemy engine
    """
    global _engine, _SessionLocal
    
    # Handle SQLite-specific configuration
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        
        # Ensure the directory exists for file-based SQLite
        if ":///" in database_url and not database_url.endswith(":memory:"):
            db_path = database_url.split("///")[-1]
            if db_path and not db_path.startswith(":"):
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    _engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        echo=False,
    )
    
    # Enable foreign keys and WAL mode for SQLite
    # WAL mode allows concurrent readers and writers
    if database_url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")  # Enable WAL for better concurrency
            cursor.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s for locks
            cursor.close()
    
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    
    logger.info("Database configured", extra={"database_url": database_url})
    return _engine


def init_database() -> None:
    """Initialize the database by creating all tables."""
    global _engine
    
    if _engine is None:
        raise RuntimeError("Database not configured. Call configure_database() first.")
    
    # Import models to ensure they're registered with Base
    from . import models  # noqa: F401
    
    Base.metadata.create_all(bind=_engine)
    _ensure_sync_runs_schema(_engine)
    logger.info("Database tables created")


def _ensure_sync_runs_schema(engine: Engine) -> None:
    """Ensure sync_runs supports new status values on SQLite."""
    if engine.url.get_backend_name() != "sqlite":
        return

    from .models import SyncRun

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='sync_runs'")
        ).fetchone()
        if not row or not row[0]:
            return
        if "queued" in row[0]:
            return

        logger.info("Migrating sync_runs schema to include queued status")
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            metadata = MetaData()
            # Reflect referenced tables so foreign keys can resolve.
            metadata.reflect(bind=conn, only=("sync_configs", "users"))
            from sqlalchemy import Table
            Table("sync_configs", metadata, autoload_with=conn)
            Table("users", metadata, autoload_with=conn)
            conn.execute(text("DROP TABLE IF EXISTS sync_runs_new"))
            conn.execute(text("DROP INDEX IF EXISTS ix_sync_runs_new_config_id"))
            conn.execute(text("DROP INDEX IF EXISTS ix_sync_runs_new_user_id"))
            new_table = SyncRun.__table__.to_metadata(metadata, name="sync_runs_new")
            new_table.create(bind=conn)

            columns = [col.name for col in SyncRun.__table__.columns]
            column_list = ", ".join(columns)
            conn.execute(
                text(
                    f"INSERT INTO sync_runs_new ({column_list}) "
                    f"SELECT {column_list} FROM sync_runs"
                )
            )
            conn.execute(text("DROP TABLE sync_runs"))
            conn.execute(text("ALTER TABLE sync_runs_new RENAME TO sync_runs"))
        finally:
            conn.execute(text("PRAGMA foreign_keys=ON"))


def get_engine() -> Engine:
    """Get the configured database engine."""
    global _engine
    if _engine is None:
        raise RuntimeError("Database not configured. Call configure_database() first.")
    return _engine


def get_session_factory() -> sessionmaker:
    """Get the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        raise RuntimeError("Database not configured. Call configure_database() first.")
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    Dependency that yields a database session.
    
    Usage in FastAPI:
        @router.get("/users")
        def list_users(db: Session = Depends(get_db)):
            ...
    """
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    
    Usage:
        with session_scope() as session:
            user = session.query(User).first()
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
