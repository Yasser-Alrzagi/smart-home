"""Real HTTP + real isolated database: commit timing, rollback, and auth."""
import uuid

import bcrypt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.database import DatabaseSession, SessionLocal, get_db
from app.core.security import get_password_hash, verify_password
from app.models import AuditEvent, AuthSession, User
from app.models.enums import UserRole
from app.schemas.user import UserCreate
from app.services.user import user_service

pytestmark = pytest.mark.db


@pytest.fixture
def account_factory():
    ids = []
    def create(password="ExamplePassword!", active=True, legacy=False):
        name = "http_" + uuid.uuid4().hex
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() if legacy else get_password_hash(password)
        with SessionLocal.begin() as db:
            user = User(username=name, email=name + "@example.com", password_hash=hashed,
                        role=UserRole.student, is_active=active)
            db.add(user)
            db.flush()
            uid = user.user_id
            ids.append(uid)
        return name, uid, hashed
    yield create
    with SessionLocal.begin() as db:
        db.execute(delete(AuditEvent).where((AuditEvent.actor_id.in_(ids)) | (AuditEvent.target_user_id.in_(ids))))
        db.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
        db.execute(delete(User).where(User.user_id.in_(ids)))


def test_real_login_and_me_do_not_expose_hash(client, account_factory):
    name, uid, _ = account_factory()
    login = client.post("/api/v1/auth/login/access-token", data={"username": name, "password": "ExamplePassword!"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = client.get("/api/v1/auth/users/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200
    assert me.json()["user_id"] == uid
    assert "password_hash" not in me.json()
    assert "password" not in me.json()


def test_long_arabic_password_is_checked_in_full_over_http(client, account_factory):
    prefix = "س" * 36
    name, _, _ = account_factory(password=prefix + "-original")
    assert client.post("/api/v1/auth/login/access-token", data={"username": name, "password": prefix + "-original"}).status_code == 200
    assert client.post("/api/v1/auth/login/access-token", data={"username": name, "password": prefix + "-different"}).status_code == 401


def test_successful_legacy_login_rehashes_and_commits(client, account_factory):
    name, uid, old_hash = account_factory(legacy=True)
    assert client.post("/api/v1/auth/login/access-token", data={"username": name, "password": "ExamplePassword!"}).status_code == 200
    with SessionLocal() as db:
        new_hash = db.get(User, uid).password_hash
        assert new_hash != old_hash
        assert new_hash.startswith("$argon2id$")
        assert verify_password("ExamplePassword!", new_hash)


def test_inactive_legacy_account_is_not_rehashed(client, account_factory):
    name, uid, old_hash = account_factory(legacy=True, active=False)
    assert client.post("/api/v1/auth/login/access-token", data={"username": name, "password": "ExamplePassword!"}).status_code == 401
    with SessionLocal() as db:
        assert db.get(User, uid).password_hash == old_hash


@pytest.mark.parametrize("failure", [False, True])
def test_http_unit_of_work_commits_or_rolls_back(failure):
    test_app = FastAPI()
    name = "request_" + uuid.uuid4().hex
    @test_app.post("/write")
    def write(db: DatabaseSession):
        user_service.create(db, user_in=UserCreate(username=name, email=name + "@example.com",
                            password="ExamplePassword!", role=UserRole.student))
        if failure:
            raise HTTPException(status_code=409, detail="Synthetic second step failed")
        return {"ok": True}
    try:
        with TestClient(test_app) as client:
            response = client.post("/write")
            assert response.status_code == (409 if failure else 200)
        with SessionLocal() as db:
            count = db.scalar(select(func.count()).select_from(User).where(User.username == name))
            assert count == (0 if failure else 1)
    finally:
        with SessionLocal.begin() as db:
            db.execute(delete(User).where(User.username == name))


def test_commit_failure_is_not_reported_as_http_success(account_factory):
    name, uid, hashed = account_factory()
    test_app = FastAPI()
    @test_app.post("/write")
    def write(db: DatabaseSession):
        # Deliberately defer the duplicate INSERT until commit at dependency exit.
        db.add(User(username=name, email="dup_" + name + "@example.com", password_hash=hashed, role=UserRole.student))
        return {"ok": True}
    with TestClient(test_app, raise_server_exceptions=False) as client:
        response = client.post("/write")
        assert response.status_code == 500
        assert response.text == "Internal Server Error"
    with SessionLocal() as db:
        assert db.get(User, uid) is not None
        assert db.scalar(select(func.count()).select_from(User).where(User.username == name)) == 1


def test_every_actual_http_db_dependency_is_function_scoped():
    from app.api.v1.auth import router
    found = []
    def walk(dependant):
        if dependant.call is get_db:
            found.append(dependant.scope)
        for sub in dependant.dependencies:
            walk(sub)
    for route in router.routes:
        walk(route.dependant)
    assert found
    assert set(found) == {"function"}
