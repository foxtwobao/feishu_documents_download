"""Database helpers for the web application."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    pass


def configure_database(path: Path) -> None:
    """Configure the SQLite engine using the provided path."""

    global _engine, _SessionLocal
    db_path = path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{db_path}"
    connect_args = {"check_same_thread": False, "timeout": 30}
    _engine = create_engine(database_url, future=True, echo=False, pool_pre_ping=True, connect_args=connect_args)
    with _engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_database() -> None:
    if _engine is None:
        raise RuntimeError("Database not configured")
    Base.metadata.create_all(bind=_engine)


def get_session() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        raise RuntimeError("Database session not configured")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def new_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database session not configured")
    return _SessionLocal()


@contextlib.contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
