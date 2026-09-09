"""Reports/export API: JSON + XML dual format, RBAC, and round-trip parse."""

import uuid
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import User
from app.models.enums import UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Reports-D9-Export-Password-2026!"


@pytest.fixture(scope="module", autouse=True)
def _clean_tables():
    with SessionLocal.begin() as db:
        db.execute(text("DELETE FROM auth_sessions"))
        db.execute(text("DELETE FROM audit_events"))
        db.execute(text("DELETE FROM users"))
    yield


@pytest.fixture
def actor(client):
    def create(role):
        name = "rep_" + uuid.uuid4().hex
        with SessionLocal.begin() as db:
            u = User(
                username=name,
                email=name + "@example.com",
                role=role,
                is_active=True,
                password_hash=get_password_hash(PASSWORD),
                must_change_password=False,
            )
            db.add(u)
            db.flush()
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": name, "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        return {"headers": {"Authorization": "Bearer " + login.json()["access_token"]}}

    return create


def test_users_json_then_xml_roundtrip(client, actor):
    admin = actor(R.system_administrator)
    r = client.get("/api/v1/reports/users", headers=admin["headers"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert "items" in body and body["format"] == "json"

    r = client.get("/api/v1/reports/users?format=xml", headers=admin["headers"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.text)
    assert root.tag == "report"
    assert root.get("type") == "users"
    usernames = [el.findtext("username") for el in root.findall("item")]
    assert usernames and all(u for u in usernames)
    # XML payload must never leak password hashes.
    assert "password" not in r.text.lower()


def test_applications_staff_ok_student_forbidden(client, actor):
    staff = actor(R.student_affairs)
    student = actor(R.student)
    ok = client.get(
        "/api/v1/reports/applications?format=xml", headers=staff["headers"]
    )
    assert ok.status_code == 200
    ET.fromstring(ok.text)
    denied = client.get(
        "/api/v1/reports/applications?format=xml", headers=student["headers"]
    )
    assert denied.status_code == 403


def test_overview_defaults_to_json(client, actor):
    admin = actor(R.system_administrator)
    r = client.get("/api/v1/reports/overview", headers=admin["headers"])
    assert r.status_code == 200
    assert r.json()["format"] == "json"
    r = client.get("/api/v1/reports/overview?format=xml", headers=admin["headers"])
    assert r.status_code == 200
    ET.fromstring(r.text)


def test_unknown_format_rejected(client, actor):
    admin = actor(R.system_administrator)
    r = client.get("/api/v1/reports/users?format=yaml", headers=admin["headers"])
    assert r.status_code in (400, 422)


def test_anonymous_rejected(client):
    r = client.get("/api/v1/reports/users?format=xml")
    assert r.status_code == 401
