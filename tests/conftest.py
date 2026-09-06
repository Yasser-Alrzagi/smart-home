"""Hermetic settings. DB tests opt in through a guarded TEST_DATABASE_URL.

No app import may appear before the environment setup below. The project's .env
is deliberately ignored. Pytest NEVER migrates/drops a database automatically.
"""
import os
import secrets

import pytest

from tests.db_safety import UnsafeTestDatabase, validate_test_url

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_URL:
    try:
        TEST_URL = validate_test_url(TEST_URL)
    except UnsafeTestDatabase as exc:
        raise pytest.UsageError(str(exc)) from None

os.environ.update(
    APP_ENV="test",
    SECRET_KEY=secrets.token_hex(48),
    DATABASE_URL=TEST_URL or "sqlite+pysqlite:///:memory:",
    DEBUG="True",
    BACKEND_CORS_ORIGINS="http://testserver",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import engine  # noqa: E402
from main import app  # noqa: E402


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        # Preserve the existing test layout while correctly classifying the DB
        # tests that historically lived under unit/ and initialization.
        needs_db = (
            "db_session" in item.fixturenames
            or "tests/integration/" in item.nodeid.replace("\\", "/")
            or item.name in {"test_health_check_endpoint", "test_database_connection"}
            or item.get_closest_marker("db") is not None
        )
        if needs_db:
            if item.get_closest_marker("db") is None:
                item.add_marker(pytest.mark.db)
            if not TEST_URL:
                item.add_marker(pytest.mark.skip(reason="Set guarded TEST_DATABASE_URL to run live DB tests."))


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()


@pytest.fixture(autouse=True)
def isolated_identity_state(request):
    """D2 tests ONLY: clear volatile security state; remove new synthetic users.

    This fixture runs only on the explicitly guarded dedicated test schema.
    Never point TEST_DATABASE_URL at an environment with data worth keeping.
    """
    if not TEST_URL or request.node.get_closest_marker("db") is None:
        yield
        return
    from sqlalchemy import delete, select
    from app.models import AuditEvent, AuthSession, LoginRateBucket, User
    with engine.begin() as conn:
        before = set(conn.execute(select(User.user_id)).scalars())
        conn.execute(delete(LoginRateBucket))
    try:
        yield
    finally:
        with engine.begin() as conn:
            new_ids = set(conn.execute(select(User.user_id)).scalars()) - before
            conn.execute(delete(AuditEvent))
            conn.execute(delete(AuthSession))
            conn.execute(delete(LoginRateBucket))
            if new_ids:
                conn.execute(delete(User).where(User.user_id.in_(new_ids)))
