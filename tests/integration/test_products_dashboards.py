"""D8 real HTTP/DB contracts: role-scoped dashboard summaries."""

import uuid

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import Student, User
from app.models.enums import AcademicStatus, HousingStatus, UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Products-D8-Test-Password-2026!"
ALL_ROLES = [
    R.student,
    R.student_affairs,
    R.housing_administration,
    R.maintenance_officer,
    R.activity_officer,
    R.food_officer,
    R.sports_officer,
    R.cleaning_officer,
    R.system_administrator,
]


@pytest.fixture(scope="module", autouse=True)
def _clean_d8_tables():
    with SessionLocal.begin() as db:
        for t in (
            "notifications", "attendance_records", "student_absences",
            "permission_requests", "emergency_reports", "service_registrations",
            "service_periods", "services", "complaints", "maintenance_requests",
            "room_assignments", "rooms", "apartments", "floors",
            "applications", "application_documents", "students",
            "auth_sessions", "audit_events", "users",
        ):
            db.execute(text(f"DELETE FROM {t}"))
    yield


@pytest.fixture
def actors(client):
    def create(role=R.student):
        name = "d8_" + uuid.uuid4().hex
        user = User(
            username=name,
            email=name + "@example.com",
            role=role,
            is_active=True,
            password_hash=get_password_hash(PASSWORD),
        )
        with SessionLocal.begin() as db:
            db.add(user)
            db.flush()
            student_id = None
            if role == R.student:
                student = Student(
                    user_id=user.user_id,
                    full_name="طالب لوحة د8",
                    university="صنعاء",
                    major="هندسة",
                    academic_status=AcademicStatus.continuing,
                    housing_status=HousingStatus.active,
                )
                db.add(student)
                db.flush()
                student_id = student.student_id
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": name, "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        return {
            "id": user.user_id,
            "username": name,
            "student_id": student_id,
            "headers": {"Authorization": "Bearer " + login.json()["access_token"]},
        }

    return create


def _stat_by_key(payload, key):
    return next((s for s in payload["stats"] if s["key"] == key), None)


def test_every_role_gets_its_own_dashboard(client, actors):
    for role in ALL_ROLES:
        actor = actors(role)
        resp = client.get("/api/v1/dashboards/me", headers=actor["headers"])
        assert resp.status_code == 200, f"{role}: {resp.text}"
        body = resp.json()
        assert body["role"] == role.value
        assert isinstance(body["stats"], list) and body["stats"]
        assert isinstance(body["actions"], list) and body["actions"]
        assert isinstance(body["latest"], list)
        for action in body["actions"]:
            assert action["page"] and action["label"]
        # Every stat has the agreed shape.
        for s in body["stats"]:
            assert set(s.keys()) == {"key", "label", "value"}


def test_affairs_sees_pending_permission_and_reports(client, actors):
    student = actors(R.student)
    affairs = actors(R.student_affairs)
    ok = client.post(
        "/api/v1/permissions",
        headers=student["headers"],
        json={
            "start_date": "2026-09-10",
            "end_date": "2026-09-10",
            "reason": "ظرف عائلي",
        },
    )
    assert ok.status_code == 201, ok.text
    resp = client.get("/api/v1/dashboards/me", headers=affairs["headers"])
    assert resp.status_code == 200
    body = resp.json()
    pending = _stat_by_key(body, "pending_permissions")
    assert pending is not None and pending["value"] >= 1
    attention_keys = {a["key"] for a in body["attention"]}
    assert "pending_permissions" in attention_keys
    assert any(it["key"] == "permission" for it in body["latest"])


def test_housing_counts_complaints_and_rooms(client, actors):
    housing = actors(R.housing_administration)
    student = actors(R.student)
    with SessionLocal.begin() as db:
        db.execute(text("INSERT INTO floors (floor_id, building_name, floor_number) VALUES (:f,'مبنى','1')"), {"f": "d8f-" + uuid.uuid4().hex[:20]})
        cur = db.execute(text("SELECT floor_id FROM floors LIMIT 1"))
        floor_id = cur.scalar()
        db.execute(text("INSERT INTO apartments (apartment_id, floor_id, apartment_number) VALUES (:a,:f,'1')"), {"a": "d8a-" + uuid.uuid4().hex[:20], "f": floor_id})
        cur = db.execute(text("SELECT apartment_id FROM apartments LIMIT 1"))
        apartment_id = cur.scalar()
        db.execute(
            text("INSERT INTO rooms (room_id, apartment_id, room_number, capacity, status) VALUES (:r,:a,'1',2,'available')"),
            {"r": "d8r-" + uuid.uuid4().hex[:20], "a": apartment_id},
        )
    complaint = client.post(
        "/api/v1/complaints",
        headers=student["headers"],
        json={"category": "نظافة", "description": "ممر غير نظيف"},
    )
    assert complaint.status_code == 201, complaint.text
    resp = client.get("/api/v1/dashboards/me", headers=housing["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert _stat_by_key(body, "rooms")["value"] >= 1
    assert _stat_by_key(body, "open_complaints")["value"] >= 1
    assert any(it["key"] == "complaint" for it in body["latest"])


def test_maintenance_and_service_officer_counts(client, actors):
    student = actors(R.student)
    maintenance = actors(R.maintenance_officer)
    officer = actors(R.activity_officer)
    req = client.post(
        "/api/v1/maintenance",
        headers=student["headers"],
        json={"problem_type": "إضاءة", "description": "المصباح مطفأ"},
    )
    assert req.status_code == 201, req.text
    body = client.get("/api/v1/dashboards/me", headers=maintenance["headers"]).json()
    assert _stat_by_key(body, "pending")["value"] >= 1
    assert any(it["key"] == "maintenance" for it in body["latest"])
    # Service officer owns a service with an open period.
    svc = client.post(
        "/api/v1/services",
        headers=officer["headers"],
        json={"service_type": "Activity", "name": "نشاط اختبار", "is_active": True},
    )
    assert svc.status_code == 201, svc.text
    period = client.post(
        "/api/v1/service-periods",
        headers=officer["headers"],
        json={
            "service_id": svc.json()["service_id"],
            "start_date": "2026-09-10",
            "end_date": "2026-10-10",
            "capacity": 20,
        },
    )
    assert period.status_code == 201, period.text
    opened = client.post(
        "/api/v1/service-periods/" + period.json()["period_id"] + "/status",
        headers=officer["headers"],
        json={"status": "Open"},
    )
    assert opened.status_code == 200, opened.text
    body = client.get("/api/v1/dashboards/me", headers=officer["headers"]).json()
    assert _stat_by_key(body, "services")["value"] >= 1
    assert _stat_by_key(body, "open_periods")["value"] >= 1
    assert any(it["key"] == "period" for it in body["latest"])


def test_admin_sees_accounts_and_student_sees_own_numbers(client, actors):
    admin = actors(R.system_administrator)
    student = actors(R.student)
    body = client.get("/api/v1/dashboards/me", headers=admin["headers"]).json()
    assert _stat_by_key(body, "total_users")["value"] >= 2
    assert any(it["key"] == "user" for it in body["latest"])
    body = client.get("/api/v1/dashboards/me", headers=student["headers"]).json()
    assert _stat_by_key(body, "applications") is not None
    assert _stat_by_key(body, "unread") is not None
