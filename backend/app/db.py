"""Connexion base de données (SQLAlchemy 2). PostgreSQL/Supabase ou SQLite."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_db_url(url: str) -> str:
    """Supabase/Render fournissent `postgres://…` ; SQLAlchemy + psycopg 3 attend `postgresql+psycopg://…`."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_db_url(url)
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _pragma(dbapi_conn, _):  # pragma: no cover - configuration
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    # prepare_threshold=None : compatible avec le pooler de Supabase (pgbouncer, mode transaction).
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
                         connect_args={"prepare_threshold": None})


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
