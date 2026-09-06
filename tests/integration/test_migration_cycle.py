"""Real DDL regression, opt-in, on a distinct EMPTY scratch schema only."""

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import BASE_DIR
from app.models import Base
from tests.db_safety import validate_test_url

pytestmark = [pytest.mark.db, pytest.mark.migration_cycle]


def test_upgrade_downgrade_upgrade_on_separate_empty_database():
    raw = os.environ.get("TEST_MIGRATION_DATABASE_URL")
    if os.environ.get("RUN_MIGRATION_CYCLE") != "1" or not raw:
        pytest.skip("Opt in with RUN_MIGRATION_CYCLE=1 and TEST_MIGRATION_DATABASE_URL")
    url = validate_test_url(raw)
    # Reject the same schema even when different aliases refer to the same host.
    assert make_url(url).database != make_url(os.environ["TEST_DATABASE_URL"]).database
    scratch = create_engine(url)
    try:
        with scratch.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert tables <= set(Base.metadata.tables) | {"alembic_version"}, (
                "Unexpected scratch tables: refusing DDL"
            )
            if "account_guard" in tables:
                assert list(
                    conn.execute(text("SELECT guard_id FROM account_guard")).scalars()
                ) == [1]
            for name in tables - {"alembic_version", "account_guard"}:
                assert (
                    conn.execute(text(f"SELECT COUNT(*) FROM `{name}`")).scalar() == 0
                ), "Scratch data exists: refusing DDL"
        env = os.environ.copy()
        env.update(APP_ENV="test", DATABASE_URL=url)

        def migrate(*args):
            proc = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=BASE_DIR,
                env=env,
                text=True,
                capture_output=True,
                timeout=60,
            )
            assert proc.returncode == 0, (
                "Migration failed; inspect locally with DSN redaction."
            )

        migrate("upgrade", "head")
        assert set(inspect(scratch).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        migrate("downgrade", "base")
        assert set(inspect(scratch).get_table_names()) <= {"alembic_version"}
        migrate("upgrade", "head")
        migrate("check")
        assert set(inspect(scratch).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        # Explicitly clean only this guarded, empty scratch schema after success.
        migrate("downgrade", "base")
    finally:
        scratch.dispose()


def test_d2_upgrade_preserves_an_existing_d1_account():
    import uuid
    from datetime import datetime
    from app.core.security import get_password_hash

    raw = os.environ.get("TEST_MIGRATION_DATABASE_URL")
    if os.environ.get("RUN_MIGRATION_CYCLE") != "1" or not raw:
        pytest.skip("Explicit empty scratch schema opt-in is required")
    url = validate_test_url(raw)
    assert make_url(url).database != make_url(os.environ["TEST_DATABASE_URL"]).database
    scratch = create_engine(url)
    env = os.environ.copy()
    env.update(APP_ENV="test", DATABASE_URL=url)

    def migrate(*args):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, (
            "Scratch migration failed; connection details redacted"
        )

    try:
        with scratch.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert tables <= set(Base.metadata.tables) | {"alembic_version"}
            for name in tables - {"alembic_version", "account_guard"}:
                assert (
                    conn.execute(text(f"SELECT COUNT(*) FROM `{name}`")).scalar() == 0
                )
        migrate("downgrade", "base")
        migrate("upgrade", "ca98ebed8d42")
        uid = str(uuid.uuid4())
        hashed = get_password_hash("PreservedLegacyPassword!")
        with scratch.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (user_id,username,email,password_hash,role,is_active,created_at,updated_at) "
                    "VALUES (:id,'legacy_d1_account','legacy@example.com',:hashed,'student',1,:now,:now)"
                ),
                {"id": uid, "hashed": hashed, "now": datetime(2026, 9, 5)},
            )
        migrate("upgrade", "head")
        with scratch.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT username,password_hash,auth_version,must_change_password FROM users WHERE user_id=:id"
                ),
                {"id": uid},
            ).one()
            assert tuple(row) == ("legacy_d1_account", hashed, 0, 0)
        migrate("downgrade", "ca98ebed8d42")
        with scratch.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT password_hash FROM users WHERE user_id=:id"),
                    {"id": uid},
                ).scalar()
                == hashed
            )
        migrate("upgrade", "head")
        with scratch.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE user_id=:id"), {"id": uid})
        migrate("check")
        migrate("downgrade", "base")
    finally:
        scratch.dispose()


def test_d3_downgrade_refuses_private_document_data():
    import uuid

    raw = os.environ.get("TEST_MIGRATION_DATABASE_URL")
    if os.environ.get("RUN_MIGRATION_CYCLE") != "1" or not raw:
        pytest.skip("Explicit scratch database opt-in required")
    url = validate_test_url(raw)
    assert make_url(url).database != make_url(os.environ["TEST_DATABASE_URL"]).database
    scratch = create_engine(url)
    env = os.environ.copy()
    env.update(APP_ENV="test", DATABASE_URL=url)

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    with scratch.connect() as conn:
        assert set(inspect(conn).get_table_names()) <= {"alembic_version"}, (
            "Use the empty scratch schema only"
        )
    assert migrate("upgrade", "head").returncode == 0
    u, s, a, d = [str(uuid.uuid4()) for _ in range(4)]
    try:
        with scratch.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (user_id,username,email,password_hash,role,is_active,created_at,updated_at) VALUES (:u,'guard_data','guard@example.com','synthetic','student',1,NOW(),NOW())"
                ),
                {"u": u},
            )
            conn.execute(
                text(
                    "INSERT INTO students (student_id,user_id,full_name,university,major,academic_status,housing_status,created_at,updated_at) VALUES (:s,:u,'Synthetic','Test','Test','continuing','active',NOW(),NOW())"
                ),
                {"s": s, "u": u},
            )
            conn.execute(
                text(
                    "INSERT INTO applications (application_id,student_id,application_date,status) VALUES (:a,:s,NOW(),'draft')"
                ),
                {"a": a, "s": s},
            )
            conn.execute(
                text(
                    "INSERT INTO application_documents (document_id,application_id,document_type,file_path,uploaded_at,content) VALUES (:d,:a,'national_id','synthetic',NOW(),:content)"
                ),
                {"d": d, "a": a, "content": b"private synthetic test content"},
            )
        refused = migrate("downgrade", "d2a5c19f0b72")
        assert (
            refused.returncode != 0
            and "refusing destructive downgrade" in refused.stderr
        )
        with scratch.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT content FROM application_documents WHERE document_id=:d"
                    ),
                    {"d": d},
                ).scalar()
                == b"private synthetic test content"
            )
            assert inspect(conn).has_table("application_events")
    finally:
        with scratch.begin() as conn:
            conn.execute(
                text("DELETE FROM application_documents WHERE document_id=:d"), {"d": d}
            )
            conn.execute(
                text("DELETE FROM applications WHERE application_id=:a"), {"a": a}
            )
            conn.execute(text("DELETE FROM students WHERE student_id=:s"), {"s": s})
            conn.execute(text("DELETE FROM users WHERE user_id=:u"), {"u": u})
        assert migrate("downgrade", "base").returncode == 0
        scratch.dispose()
