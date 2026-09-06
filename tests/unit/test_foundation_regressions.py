"""Regression contracts captured before the foundation fixes (D1)."""
import os
import subprocess
import sys
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from app.core.config import BASE_DIR, Settings, settings
from app.core.database import SessionLocal, get_db
from app.core.security import get_password_hash, verify_password
from app.models import User
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services.user import user_service
from main import app


def valid_user(**overrides):
    data = dict(username="example", email="example@example.com", password="safe-password", role=UserRole.student)
    data.update(overrides)
    return UserCreate(**data)


@pytest.mark.parametrize("prefix", ["A" * 72, "س" * 36])
def test_password_suffix_after_72_bytes_matters(prefix):
    hashed = get_password_hash(prefix + "-original")
    assert verify_password(prefix + "-original", hashed)
    assert not verify_password(prefix + "-different", hashed)


def test_new_hashes_are_argon2id():
    assert get_password_hash("safe-password").startswith("$argon2id$")


def test_hash_creation_rejects_oversized_password():
    with pytest.raises(ValueError):
        get_password_hash("a" * 257)


@pytest.mark.parametrize("field", ["username", "email", "role", "is_active", "password"])
def test_explicit_null_is_rejected_in_patch(field):
    with pytest.raises(ValidationError):
        UserUpdate(**{field: None})


def test_omitted_patch_fields_remain_omitted():
    assert UserUpdate().model_dump(exclude_unset=True) == {}
    assert UserUpdate(is_active=False).model_dump(exclude_unset=True) == {"is_active": False}


def test_whitespace_only_username_is_rejected():
    with pytest.raises(ValidationError):
        valid_user(username="   ")


def test_username_is_trimmed_but_password_is_not():
    user = valid_user(username="  alice  ", password="  password  ")
    assert user.username == "alice"
    assert user.password == "  password  "


def test_email_cannot_exceed_database_width():
    with pytest.raises(ValidationError):
        valid_user(email="a" * 260 + "@example.com")


@pytest.mark.parametrize("password", ["p@ss", "a:b/c%#?", "عربي@/%", "with space", "plain"])
def test_database_password_round_trips(password):
    config = Settings(_env_file=None, SECRET_KEY=settings.SECRET_KEY, DATABASE_URL=None, DB_PASSWORD=password)
    url = make_url(config.get_database_url)
    assert url.password == password
    assert url.host == config.DB_HOST


def test_encoded_database_url_supports_alembic_offline(tmp_path):
    env = os.environ.copy()
    env["DATABASE_URL"] = "mysql+pymysql://lab:p%40ss%25@localhost/smart_home_test?charset=utf8mb4"
    proc = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
                          cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=30)
    # Do not include the subprocess output in assertion messages: DSNs may contain secrets.
    assert proc.returncode == 0
    assert "CREATE TABLE users" in proc.stdout


@pytest.mark.db
def test_request_session_commits_on_success():
    name = "atomic_" + uuid.uuid4().hex
    dep = get_db()
    try:
        db = next(dep)
        user = user_service.create(db, user_in=valid_user(username=name, email=name + "@example.com"))
        uid = user.user_id
        with pytest.raises(StopIteration):
            next(dep)
        with SessionLocal() as other:
            assert other.get(User, uid) is not None
    finally:
        dep.close()
        with SessionLocal.begin() as cleanup:
            cleanup.execute(delete(User).where(User.username == name))


@pytest.mark.db
def test_request_session_rolls_back_on_failure():
    name = "rollback_" + uuid.uuid4().hex
    dep = get_db()
    db = next(dep)
    user = user_service.create(db, user_in=valid_user(username=name, email=name + "@example.com"))
    uid = user.user_id
    with pytest.raises(RuntimeError, match="synthetic failure"):
        dep.throw(RuntimeError("synthetic failure"))
    with SessionLocal() as other:
        assert other.get(User, uid) is None


def test_oversized_login_is_controlled_for_existing_and_missing_users(db_session, client, monkeypatch):
    user_service.create(db_session, user_in=valid_user(username="boundary_user"))
    monkeypatch.setitem(app.dependency_overrides, get_db, lambda: db_session)
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        for username in ["boundary_user", "missing_boundary_user"]:
            response = safe_client.post("/api/v1/auth/login/access-token", data={"username": username, "password": "x" * 5000})
            assert response.status_code == 422
            assert "x" * 100 not in response.text


def test_corrupt_documented_enum_value_is_detected(monkeypatch):
    from tests.unit import test_docs_schema
    path = test_docs_schema.DOC_PATH
    original = path.read_text(encoding="utf-8")
    corrupted = original.replace('| `user_role` | student,', '| `user_role` | INVALID_VALUE,', 1)
    assert corrupted != original
    original_reader = type(path).read_text
    def reader(self, *args, **kwargs):
        return corrupted if self == path else original_reader(self, *args, **kwargs)
    monkeypatch.setattr(type(path), "read_text", reader)
    with pytest.raises(AssertionError):
        test_docs_schema.test_documented_enum_value_sets_match_the_python_enums()


@pytest.mark.parametrize("value", ["x" * 256, "س" * 256, "  spaces are significant  "])
def test_allowed_password_boundaries_are_preserved(value):
    hashed = get_password_hash(value)
    assert verify_password(value, hashed)
    assert not verify_password(value[:-1], hashed)


@pytest.mark.parametrize("hash_value", ["not-a-hash", "$argon2id$broken", "$2b$broken", None])
def test_invalid_stored_hash_is_a_failed_verification(hash_value):
    assert not verify_password("valid-password", hash_value)


def test_legacy_bcrypt_never_accepts_over_72_bytes():
    import bcrypt
    hashed = bcrypt.hashpw(b"a" * 72, bcrypt.gensalt()).decode()
    assert verify_password("a" * 72, hashed)
    assert not verify_password("a" * 72 + "suffix", hashed)


def test_lone_surrogate_password_is_rejected():
    with pytest.raises(ValidationError):
        valid_user(password="abcdefgh" + "\ud800")


def test_retired_assembler_cannot_overwrite_migration():
    revision = BASE_DIR / "alembic/versions/ca98ebed8d42_initial_schema_all_22_tables.py"
    before = revision.read_bytes()
    proc = subprocess.run([sys.executable, str(BASE_DIR / "_assemble_revision.py")],
                          cwd=BASE_DIR, capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0
    assert "retired" in proc.stderr
    assert revision.read_bytes() == before
