"""SQLAlchemy engine/session for the historical subsystem.

Uses DATABASE_URL (e.g. postgresql+psycopg://user:pass@localhost:5432/aegis). If your project
already has an engine/session factory, point `get_engine` at it and keep everything else.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.historical import settings


class DatabaseNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    url = url or settings.database_url()
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs.pop("pool_pre_ping")
    else:
        kwargs["connect_args"] = {"connect_timeout": 5}
    return create_engine(url, **kwargs)


def get_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    session = get_sessionmaker(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_schema(url: str | None = None) -> None:
    """Create the historical tables if missing (idempotent). Prefer Alembic if you use it."""
    from app.historical.models import HistoricalBase
    HistoricalBase.metadata.create_all(get_engine(url))
