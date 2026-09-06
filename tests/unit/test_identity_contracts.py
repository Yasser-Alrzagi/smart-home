from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
import uuid

import jwt
import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import BASE_DIR, settings
from app.core.errors import AppError
from app.core.security import create_access_token, decode_access_token
from app.schemas.identity import AdminAccountUpdate, PasswordChange, SelfProfileUpdate
from app.services import rate_limit


def valid_claims():
    now = int(datetime.now(timezone.utc).timestamp())
    return dict(
        sub=str(uuid.uuid4()),
        jti=str(uuid.uuid4()),
        ver=0,
        type="access",
        iat=now,
        exp=now + 1800,
        iss=settings.JWT_ISSUER,
        aud=settings.JWT_AUDIENCE,
        role="Student",
    )


def signed(payload):
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


@pytest.mark.parametrize(
    "field", ["exp", "iat", "sub", "jti", "ver", "type", "iss", "aud"]
)
def test_jwt_requires_every_security_claim(field):
    claims = valid_claims()
    claims.pop(field)
    assert decode_access_token(signed(claims)) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "refresh"),
        ("ver", -1),
        ("ver", "0"),
        ("ver", True),
        ("jti", "not-a-uuid"),
        ("iss", "other-service"),
        ("aud", "other-api"),
        ("aud", ["smart-student-housing-api"]),
        ("sub", ""),
        ("iat", "0"),
    ],
)
def test_invalid_claim_contract_is_rejected(field, value):
    claims = valid_claims()
    claims[field] = value
    assert decode_access_token(signed(claims)) is None


def test_valid_token_and_wrong_signature_and_expiry():
    token = create_access_token("user-id", "Student")
    assert decode_access_token(token) is not None
    assert (
        decode_access_token(
            jwt.encode(
                valid_claims(),
                "different-key-with-more-than-32-characters",
                algorithm="HS256",
            )
        )
        is None
    )
    assert (
        decode_access_token(
            create_access_token("user-id", "Student", timedelta(seconds=-1))
        )
        is None
    )
    assert decode_access_token("x" * 4097) is None


@pytest.mark.parametrize("schema", [SelfProfileUpdate, AdminAccountUpdate])
def test_profile_nulls_are_rejected_not_silently_ignored(schema):
    with pytest.raises(ValueError):
        schema(email=None)
    assert schema().model_dump(exclude_unset=True) == {}


def test_password_policy_is_twelve_characters_for_new_passwords():
    with pytest.raises(ValueError):
        PasswordChange(current_password="old-password", new_password="12345678901")


def test_limiter_fails_closed_on_database_error(monkeypatch):
    def unavailable():
        raise OperationalError("redacted", {}, Exception("test outage"))

    monkeypatch.setattr(rate_limit, "session_scope", unavailable)
    with pytest.raises(AppError) as result:
        rate_limit.consume("a" * 64, limit=1, seconds=60)
    assert result.value.status_code == 503


def test_rate_keys_are_keyed_and_do_not_store_input():
    key = rate_limit.opaque_key("test", "192.0.2.1:student-name")
    assert len(key) == 64 and "student" not in key
    assert key != rate_limit.opaque_key("different-scope", "192.0.2.1:student-name")


def test_schema_head_contract_matches_alembic_graph():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.core.schema_version import SCHEMA_HEAD

    script = ScriptDirectory.from_config(Config(str(BASE_DIR / "alembic.ini")))
    assert script.get_heads() == [SCHEMA_HEAD]
    assert script.get_revision(SCHEMA_HEAD).down_revision == "d2a5c19f0b72"


def test_no_password_option_in_bootstrap_cli():
    proc = subprocess.run(
        [sys.executable, "-m", "tools.bootstrap_admin", "--help"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "--password-stdin" in proc.stdout
    assert "--password " not in proc.stdout


def test_dependency_declaration_replaces_python_jose():
    import tomllib

    project = tomllib.loads((BASE_DIR / "pyproject.toml").read_text())
    assert not any("python-jose" in item for item in project["project"]["dependencies"])
    assert any(item.startswith("PyJWT") for item in project["project"]["dependencies"])


def test_unknown_account_runs_password_verification(db_session, monkeypatch):
    from app.services import auth

    seen = []
    monkeypatch.setattr(
        auth, "verify_password", lambda plain, hashed: seen.append(hashed) or False
    )
    assert (
        auth.auth_service.authenticate(
            db_session, username="unknown_timing_user", password="wrong-password"
        )
        is None
    )
    assert len(seen) == 1 and seen[0].startswith("$argon2id$")


def test_readiness_fails_closed_on_stale_schema(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "SCHEMA_HEAD", "not_the_installed_revision")
    assert client.get("/ready").status_code == 503


@pytest.mark.db
def test_bootstrap_cli_stdin_is_one_time_and_does_not_echo_password():
    password = "SyntheticBootstrapSecret-2026!"
    args = [
        sys.executable,
        "-m",
        "tools.bootstrap_admin",
        "--username",
        "cli_first_admin",
        "--email",
        "cli-admin@example.com",
        "--password-stdin",
    ]
    proc = subprocess.run(
        args,
        cwd=BASE_DIR,
        env=os.environ.copy(),
        input=password + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0
    assert password not in proc.stdout + proc.stderr
    repeat = subprocess.run(
        args,
        cwd=BASE_DIR,
        env=os.environ.copy(),
        input=password + "\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert repeat.returncode != 0
    assert "already exists" in repeat.stderr
    assert password not in repeat.stdout + repeat.stderr


def test_secret_fields_are_not_exposed_in_model_reprs():
    from app.core.config import Settings
    from app.schemas.identity import BootstrapAdmin
    from app.schemas.user import Token, UserCreate, UserUpdate

    secret = "DoNotPrintThisSecret-2026!"
    objects = [
        PasswordChange(current_password=secret, new_password=secret),
        BootstrapAdmin(username="admin", email="admin@example.com", password=secret),
        UserCreate(
            username="student",
            email="student@example.com",
            password=secret,
            role="Student",
        ),
        UserUpdate(password=secret),
        Token(access_token=secret, token_type="bearer"),
        Settings(
            _env_file=None,
            SECRET_KEY=secret * 2,
            DB_PASSWORD=secret,
            DATABASE_URL=f"mysql+pymysql://user:{secret}@localhost/db",
        ),
    ]
    for value in objects:
        assert secret not in repr(value)


def test_rejected_bootstrap_password_argument_is_redacted():
    secret = "DoNotEchoAnAccidentalArgvSecret"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.bootstrap_admin",
            "--username",
            "admin",
            "--email",
            "admin@example.com",
            "--password",
            secret,
        ],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert secret not in proc.stdout + proc.stderr
