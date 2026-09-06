"""One unit of work per request; repositories flush, this boundary commits."""
from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(settings.get_database_url, pool_pre_ping=True, pool_recycle=3600, echo=False)
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, bind=engine)
Base = declarative_base()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Own a complete transaction. Commit on success; rollback and close on failure.

    Use this for jobs/CLI code too. Do not use the yielded session after leaving
    the context or call commit inside repositories/business sub-operations.
    """
    with SessionLocal.begin() as db:
        yield db


def get_db() -> Generator[Session, None, None]:
    """HTTP adapter. Always consume through DatabaseSession (function scope)."""
    with session_scope() as db:
        yield db


# FastAPI >=0.121: finalize the transaction BEFORE a successful response is sent.
# Request-scoped yield cleanup is too late to report a commit error to the client.
DatabaseSession = Annotated[Session, Depends(get_db, scope="function")]
