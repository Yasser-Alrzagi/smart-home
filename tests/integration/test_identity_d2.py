"""D2 acceptance tests against real MariaDB and the actual HTTP routers."""

from concurrent.futures import ThreadPoolExecutor
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.errors import AppError, HardDeleteDisabled
from app.core.security import decode_access_token, get_password_hash
from app.models import (
    AuditEvent,
    AuthSession,
    LoginRateBucket,
    Student,
    StudentStatusHistory,
    User,
)
from app.models.enums import StatusType, UserRole
from app.schemas.identity import AdminAccountUpdate, BootstrapAdmin
from app.services import accounts
from app.services.rate_limit import consume, opaque_key
from app.services.sessions import resolve_context
from main import app

pytestmark = pytest.mark.db
PASSWORD = "ExamplePassword-2026!"
NEW_PASSWORD = "DifferentPassword-2026!"


@pytest.fixture
def actor(client):
    def make(
        role=UserRole.student, *, active=True, must_change=False, password=PASSWORD
    ):
        name = "identity_" + uuid.uuid4().hex
        with SessionLocal.begin() as db:
            user = User(
                username=name,
                email=name + "@example.com",
                role=role,
                is_active=active,
                password_hash=get_password_hash(password),
                must_change_password=must_change,
            )
            db.add(user)
            db.flush()
            uid = user.user_id
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": name, "password": password},
        )
        token = response.json().get("access_token")
        return {
            "name": name,
            "id": uid,
            "password": password,
            "token": token,
            "headers": {"Authorization": "Bearer " + token} if token else {},
            "login": response,
        }

    return make


def login(client, account, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login/access-token",
        data={"username": account["name"], "password": password},
    )


def new_account_data():
    name = "created_" + uuid.uuid4().hex
    return dict(
        username=name, email=name + "@example.com", role="Student", password=PASSWORD
    )


@pytest.mark.parametrize("role", list(UserRole))
def test_role_matrix_self_service_and_account_administration(role, actor, client):
    user = actor(role)
    other = actor()
    h = user["headers"]
    assert client.get("/api/v1/auth/users/me", headers=h).status_code == 200
    assert (
        client.patch(
            "/api/v1/auth/users/me",
            headers=h,
            json={"email": user["name"] + "@new.example.com"},
        ).status_code
        == 200
    )
    admin = role == UserRole.system_administrator
    checks = [
        (client.get("/api/v1/users", headers=h), 200),
        (client.get("/api/v1/users/" + other["id"], headers=h), 200),
        (client.post("/api/v1/users", headers=h, json=new_account_data()), 201),
        (
            client.patch(
                "/api/v1/users/" + other["id"],
                headers=h,
                json={"email": other["name"] + "@new.example.com"},
            ),
            200,
        ),
        (
            client.post(
                "/api/v1/users/" + other["id"] + "/reset-password",
                headers=h,
                json={"new_password": NEW_PASSWORD},
            ),
            204,
        ),
        (client.get("/api/v1/audit-events", headers=h), 200),
    ]
    for response, allowed in checks:
        assert response.status_code == (allowed if admin else 403)


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "System Administrator"),
        ("is_active", True),
        ("auth_version", 0),
        ("must_change_password", False),
        ("password_hash", "NEVER_ECHO_THIS_SECRET"),
        ("user_id", "another-id"),
    ],
)
def test_self_profile_cannot_mass_assign_privileged_fields(field, value, actor, client):
    user = actor()
    response = client.patch(
        "/api/v1/auth/users/me", headers=user["headers"], json={field: value}
    )
    assert response.status_code == 422
    assert "NEVER_ECHO_THIS_SECRET" not in response.text
    with SessionLocal() as db:
        assert db.get(User, user["id"]).role == UserRole.student


def test_no_public_registration_or_account_deletion(actor, client):
    assert client.post("/api/v1/users", json=new_account_data()).status_code == 401
    assert (
        client.post("/api/v1/auth/register", json=new_account_data()).status_code == 404
    )
    admin = actor(UserRole.system_administrator)
    student = actor()
    assert (
        client.delete(
            "/api/v1/users/" + student["id"], headers=admin["headers"]
        ).status_code
        == 405
    )
    with SessionLocal.begin() as db:
        from app.services.user import user_service

        with pytest.raises(HardDeleteDisabled):
            user_service.remove(db, user_id=student["id"])


def test_admin_provisioning_requires_password_change(actor, client):
    admin = actor(UserRole.system_administrator)
    data = new_account_data()
    created = client.post("/api/v1/users", headers=admin["headers"], json=data)
    assert created.status_code == 201
    assert created.json()["must_change_password"] is True
    assert "password_hash" not in created.json() and "password" not in created.json()
    result = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": data["username"], "password": PASSWORD},
    )
    assert (
        result.status_code == 200 and result.json()["password_change_required"] is True
    )
    h = {"Authorization": "Bearer " + result.json()["access_token"]}
    assert client.get("/api/v1/auth/users/me", headers=h).status_code == 200
    assert (
        client.patch(
            "/api/v1/auth/users/me", headers=h, json={"username": "blocked_change"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=h,
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/users/me", headers=h).status_code == 401
    fresh = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": data["username"], "password": NEW_PASSWORD},
    )
    assert (
        fresh.status_code == 200 and fresh.json()["password_change_required"] is False
    )


def test_password_change_revokes_all_sessions(actor, client):
    user = actor()
    second = login(client, user).json()["access_token"]
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=user["headers"],
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        ).status_code
        == 204
    )
    for token in (user["token"], second):
        assert (
            client.get(
                "/api/v1/auth/users/me", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 401
        )
    assert login(client, user).status_code == 401
    assert login(client, user, NEW_PASSWORD).status_code == 200


def test_wrong_current_password_does_not_change_credentials(actor, client):
    user = actor()
    assert (
        client.post(
            "/api/v1/auth/change-password",
            headers=user["headers"],
            json={
                "current_password": "wrong-current-password",
                "new_password": NEW_PASSWORD,
            },
        ).status_code
        == 400
    )
    assert (
        client.get("/api/v1/auth/users/me", headers=user["headers"]).status_code == 200
    )
    assert login(client, user).status_code == 200


def test_admin_reset_requires_change_and_revokes_tokens(actor, client):
    admin = actor(UserRole.system_administrator)
    user = actor()
    assert (
        client.post(
            f"/api/v1/users/{user['id']}/reset-password",
            headers=admin["headers"],
            json={"new_password": NEW_PASSWORD},
        ).status_code
        == 204
    )
    assert (
        client.get("/api/v1/auth/users/me", headers=user["headers"]).status_code == 401
    )
    assert login(client, user).status_code == 401
    fresh = login(client, user, NEW_PASSWORD)
    assert fresh.status_code == 200 and fresh.json()["password_change_required"]
    assert (
        client.post(
            f"/api/v1/users/{admin['id']}/reset-password",
            headers=admin["headers"],
            json={"new_password": NEW_PASSWORD},
        ).status_code
        == 409
    )


def test_role_change_disable_and_reenable_do_not_restore_old_tokens(actor, client):
    admin = actor(UserRole.system_administrator)
    user = actor()
    url = f"/api/v1/users/{user['id']}"
    assert (
        client.patch(
            url, headers=admin["headers"], json={"role": "Food Officer"}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/auth/users/me", headers=user["headers"]).status_code == 401
    )
    token = login(client, user).json()["access_token"]
    assert (
        client.patch(
            url, headers=admin["headers"], json={"is_active": False}
        ).status_code
        == 200
    )
    assert login(client, user).status_code == 401
    assert (
        client.patch(
            url, headers=admin["headers"], json={"is_active": True}
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/auth/users/me", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 401
    )
    assert login(client, user).status_code == 200


def test_logout_one_all_and_foreign_session_isolation(actor, client):
    user, other = actor(), actor()
    second = login(client, user).json()["access_token"]
    other_sid = decode_access_token(other["token"])["jti"]
    assert (
        client.delete(
            "/api/v1/auth/sessions/" + other_sid, headers=user["headers"]
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/auth/users/me", headers=other["headers"]).status_code == 200
    )
    mine = client.get("/api/v1/auth/sessions", headers=user["headers"]).json()
    assert {x["session_id"] for x in mine} == {
        decode_access_token(user["token"])["jti"],
        decode_access_token(second)["jti"],
    }
    assert (
        client.post("/api/v1/auth/logout", headers=user["headers"]).status_code == 204
    )
    assert (
        client.get("/api/v1/auth/users/me", headers=user["headers"]).status_code == 401
    )
    h = {"Authorization": "Bearer " + second}
    assert client.get("/api/v1/auth/users/me", headers=h).status_code == 200
    assert client.post("/api/v1/auth/logout-all", headers=h).status_code == 204
    assert client.get("/api/v1/auth/users/me", headers=h).status_code == 401


def test_session_cap_revokes_the_oldest(actor, client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_ACTIVE_SESSIONS", 2)
    user = actor()
    second = login(client, user).json()["access_token"]
    third = login(client, user).json()["access_token"]
    assert (
        client.get("/api/v1/auth/users/me", headers=user["headers"]).status_code == 401
    )
    for token in (second, third):
        assert (
            client.get(
                "/api/v1/auth/users/me", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 200
        )


def test_mutations_cannot_remove_last_admin_or_demote_self(actor, client):
    admin = actor(UserRole.system_administrator)
    for patch in ({"is_active": False}, {"role": "Student"}):
        assert (
            client.patch(
                f"/api/v1/users/{admin['id']}", headers=admin["headers"], json=patch
            ).status_code
            == 409
        )
    with SessionLocal() as db:
        assert db.get(User, admin["id"]).is_active


@pytest.mark.parametrize("round_number", range(5))
def test_competing_admin_disables_preserve_one_active_admin(actor, round_number):
    a, b = actor(UserRole.system_administrator), actor(UserRole.system_administrator)

    def disable(who, target):
        try:
            with SessionLocal.begin() as db:
                ctx = resolve_context(db, who["token"])
                accounts.update_account(
                    db, ctx, target["id"], AdminAccountUpdate(is_active=False)
                )
            return 200
        except AppError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(disable, a, b), pool.submit(disable, b, a)]
        results = [f.result(timeout=20) for f in futures]
    assert results.count(200) == 1
    assert all(x in {200, 401, 403, 409} for x in results)
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.role == UserRole.system_administrator, User.is_active.is_(True)
                )
            )
            == 1
        )


def test_bootstrap_is_singleton_even_under_concurrency():
    def create(i):
        try:
            with SessionLocal.begin() as db:
                user = accounts.bootstrap_admin(
                    db,
                    BootstrapAdmin(
                        username=f"first_admin_{i}",
                        email=f"first{i}@example.com",
                        password=PASSWORD,
                    ),
                )
                uid = user.user_id
            return uid
        except AppError as exc:
            assert exc.status_code == 409
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [1, 2]))
    assert sum(x is not None for x in results) == 1
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.system_administrator)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "account.bootstrap")
            )
            == 1
        )


def test_duplicate_create_is_409_and_not_audited_as_success(actor, client):
    admin = actor(UserRole.system_administrator)
    data = new_account_data()
    assert (
        client.post("/api/v1/users", headers=admin["headers"], json=data).status_code
        == 201
    )
    response = client.post("/api/v1/users", headers=admin["headers"], json=data)
    assert response.status_code == 409
    assert data["password"] not in response.text
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "account.create")
            )
            == 1
        )


def test_audit_is_redacted_and_orm_append_only(actor, client):
    admin = actor(UserRole.system_administrator)
    data = new_account_data()
    client.post("/api/v1/users", headers=admin["headers"], json=data)
    response = client.get("/api/v1/audit-events", headers=admin["headers"])
    assert response.status_code == 200
    assert PASSWORD not in response.text and data["email"] not in response.text
    assert admin["token"] not in response.text
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).limit(1))
        event.details = '{"tampered":true}'
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()
        event = db.scalar(select(AuditEvent).limit(1))
        db.delete(event)
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()


def test_deactivation_preserves_student_history(actor, client):
    admin, student = actor(UserRole.system_administrator), actor()
    with SessionLocal.begin() as db:
        profile = Student(
            user_id=student["id"],
            full_name="Synthetic Student",
            university="Test University",
            major="CS",
        )
        db.add(profile)
        db.flush()
        sid = profile.student_id
        db.add(
            StudentStatusHistory(
                student_id=sid, status_type=StatusType.housing, new_status="Active"
            )
        )
    assert (
        client.patch(
            f"/api/v1/users/{student['id']}",
            headers=admin["headers"],
            json={"is_active": False},
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        assert db.get(Student, sid) is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(StudentStatusHistory)
                .where(StudentStatusHistory.student_id == sid)
            )
            == 1
        )


def test_login_limits_persist_and_forwarded_header_cannot_bypass(
    actor, client, monkeypatch
):
    user = actor()
    monkeypatch.setattr(settings, "LOGIN_ACCOUNT_IP_LIMIT", 3)
    # The successful initial login already consumed the first slot.
    for name in (user["name"], user["name"].upper()):
        assert (
            client.post(
                "/api/v1/auth/login/access-token",
                data={"username": name, "password": "WrongPassword-2026"},
            ).status_code
            == 401
        )
    response = client.post(
        "/api/v1/auth/login/access-token",
        headers={"X-Forwarded-For": "203.0.113.111"},
        data={"username": user["name"], "password": "WrongPassword-2026"},
    )
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    with TestClient(app, client=("198.51.100.2", 50000)) as different_source:
        assert login(different_source, user).status_code == 200


def test_ip_bucket_limits_rotating_unknown_accounts(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_IP_LIMIT", 2)
    for i in range(2):
        assert (
            client.post(
                "/api/v1/auth/login/access-token",
                data={"username": f"unknown_{i}", "password": PASSWORD},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "unknown_next", "password": PASSWORD},
        ).status_code
        == 429
    )


def test_failed_login_audit_is_committed_and_pseudonymous(client):
    raw_name, raw_password = "DoNotStoreThisUsername", "DoNotStoreThisPassword"
    assert (
        client.post(
            "/api/v1/auth/login/access-token",
            data={"username": raw_name, "password": raw_password},
        ).status_code
        == 401
    )
    with SessionLocal() as db:
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "login.failure")
        )
        assert event is not None
        assert (
            raw_name not in event.details
            and raw_password not in event.details
            and "testclient" not in event.details
        )
        assert all(len(v) == 64 for v in json.loads(event.details).values())


def test_atomic_rate_limit_across_connections():
    key = opaque_key("concurrency_test", uuid.uuid4().hex)
    now = time.time()

    def attempt(_):
        try:
            consume(key, limit=3, seconds=60, now=now)
            return 200
        except AppError as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count(200) == 3 and results.count(429) == 5
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(LoginRateBucket.attempts).where(
                    LoginRateBucket.bucket_key == key
                )
            )
            == 4
        )


def test_sensitive_responses_are_not_cacheable_and_dates_are_utc(actor, client):
    user = actor()
    response = client.get("/api/v1/auth/users/me", headers=user["headers"])
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["created_at"].endswith("Z")
    assert client.get("/ready").status_code == 200


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_admin_pagination_is_bounded(query, actor, client):
    admin = actor(UserRole.system_administrator)
    assert (
        client.get("/api/v1/users?" + query, headers=admin["headers"]).status_code
        == 422
    )


def test_forged_role_claim_does_not_grant_admin_and_session_is_required(actor, client):
    from app.core.security import create_access_token

    user = actor()
    claims = decode_access_token(user["token"])
    elevated_claim = create_access_token(
        user["id"],
        "System Administrator",
        session_id=claims["jti"],
        token_version=claims["ver"],
    )
    h = {"Authorization": "Bearer " + elevated_claim}
    assert client.get("/api/v1/auth/users/me", headers=h).json()["role"] == "Student"
    assert client.get("/api/v1/users", headers=h).status_code == 403
    unknown_session = create_access_token(user["id"], "Student")
    assert (
        client.get(
            "/api/v1/auth/users/me",
            headers={"Authorization": "Bearer " + unknown_session},
        ).status_code
        == 401
    )


def test_database_session_expiry_is_checked(actor, client):
    from app.models import utcnow
    from datetime import timedelta

    user = actor()
    sid = decode_access_token(user["token"])["jti"]
    with SessionLocal.begin() as db:
        db.get(AuthSession, sid).expires_at = utcnow() - timedelta(seconds=1)
    assert (
        client.get("/api/v1/auth/users/me", headers=user["headers"]).status_code == 401
    )


def test_account_update_db_conflict_is_409_and_rolled_back(actor, client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    user = actor()

    def conflict(db):
        raise OperationalError("private sql", {}, Exception(1213, "private details"))

    monkeypatch.setattr(accounts, "_flush", conflict)
    response = client.patch(
        "/api/v1/auth/users/me",
        headers=user["headers"],
        json={"username": "rolled_back_name"},
    )
    assert response.status_code == 409 and "private" not in response.text
    with SessionLocal() as db:
        assert db.get(User, user["id"]).username == user["name"]


def test_audit_failure_rolls_back_account_creation(actor, monkeypatch):
    admin = actor(UserRole.system_administrator)
    data = new_account_data()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(accounts, "record_event", fail)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert (
            client.post(
                "/api/v1/users", headers=admin["headers"], json=data
            ).status_code
            == 500
        )
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == data["username"])) is None


def test_pruning_is_dry_run_by_default_and_removes_only_expired_buckets():
    import os
    import subprocess
    import sys
    from datetime import timedelta
    from app.models import utcnow
    from app.core.config import BASE_DIR

    with SessionLocal.begin() as db:
        db.add(
            LoginRateBucket(
                bucket_key="a" * 64,
                window_start=1,
                attempts=1,
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        db.add(
            LoginRateBucket(
                bucket_key="b" * 64,
                window_start=2,
                attempts=1,
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
    args = [sys.executable, "-m", "tools.prune_login_limits"]
    for apply, expected in [(False, 2), (True, 1)]:
        proc = subprocess.run(
            args + (["--apply"] if apply else []),
            cwd=BASE_DIR,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0
        with SessionLocal() as db:
            assert (
                db.scalar(select(func.count()).select_from(LoginRateBucket)) == expected
            )
