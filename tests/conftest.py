"""Shared pytest fixtures.

Tests run against the same MySQL database defined in .env — no second database is
created. Every ``db_session`` test runs inside an outer transaction that is rolled
back on teardown, so no test leaves rows behind.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import engine
from main import app


@pytest.fixture(scope="session")
def client():
    """TestClient used as a context manager so application lifespan actually runs."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    """Transactional session: everything written during a test is rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
