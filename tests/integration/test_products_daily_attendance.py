"""D7 real HTTP/DB contracts: daily attendance ledger + unauthorized absences."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import Student, User
from app.models.enums import AcademicStatus, HousingStatus, UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Products-D7-Test-Password-2026!"
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture(scope="module", autouse=True)
def _clean_d7_tables():
    with SessionLocal.begin() as db:
        db.execute(text("DELETE FROM attendance_records"))
        db.execute(text("DELETE FROM student_absences"))
        db.execute(text("DELETE FROM permission_requests"))
        db.execute(text("DELETE FROM emergency_reports"))
        db.execute(text("DELETE FROM audit_events"))
        db.execute(text("DELETE FROM auth_sessions"))
        db.execute(text("DELETE FROM users"))
    yield


@pytest.fixture
def actors(client):
    def create(role=R.student):
        name = "d7_" + uuid.uuid4().hex
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
                    full_name="طالب اختبار د7",
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


def _absence_count(db, student_id, source=None):
    q = (
        "SELECT COUNT(*) FROM student_absences WHERE student_id = :sid"
        + (" AND source LIKE :src" if source else "")
    )
    return db.execute(text(q), {"sid": student_id, "src": source}).scalar()


def _record(client, headers, day, entries, expect=201):
    resp = client.post(
        "/api/v1/attendance/daily",
        headers=headers,
        json={"record_date": day.isoformat(), "records": entries},
    )
    assert resp.status_code == expect, resp.text
    return resp


def test_bulk_record_generates_unauthorized_absence(client, actors):
    housing = actors(R.housing_administration)
    stu = actors(R.student)
    day = YESTERDAY
    resp = _record(
        client,
        housing["headers"],
        day,
        [
            {"student_id": stu["student_id"], "status": "Absent", "notes": "تغيب"},
            {"student_id": stu["student_id"], "status": "Present"},
        ],
    )
    body = resp.json()
    assert len(body["items"]) == 2
    with SessionLocal.begin() as db:
        assert _absence_count(db, stu["student_id"], "attendance:%") == 1
    assert body["items"][0]["absence_id"] is not None, body


def test_upsert_keeps_one_record_and_absence_is_documented(client, actors):
    housing = actors(R.housing_administration)
    stu = actors(R.student)
    day = YESTERDAY
    _record(client, housing["headers"], day, [{"student_id": stu["student_id"], "status": "Absent"}])
    with SessionLocal.begin() as db:
        count1 = db.execute(
            text("SELECT COUNT(*) FROM attendance_records WHERE student_id=:s AND record_date=:d"),
            {"s": stu["student_id"], "d": day},
        ).scalar()
        assert count1 == 1
        ab1 = _absence_count(db, stu["student_id"])
    # Corrected to present: same single row, absence history preserved.
    _record(client, housing["headers"], day, [{"student_id": stu["student_id"], "status": "Present"}])
    with SessionLocal.begin() as db:
        count2 = db.execute(
            text("SELECT COUNT(*) FROM attendance_records WHERE student_id=:s AND record_date=:d"),
            {"s": stu["student_id"], "d": day},
        ).scalar()
        assert count2 == 1
        assert _absence_count(db, stu["student_id"]) == ab1


def test_approved_permission_covers_absence(client, actors):
    housing = actors(R.housing_administration)
    stu = actors(R.student)
    day = YESTERDAY
    with SessionLocal.begin() as db:
        db.execute(
            text(
                "INSERT INTO permission_requests (permission_id, student_id, status,"
                " start_date, end_date, reason) VALUES"
                " (:pid, :sid, 'approved', :s, :e, 'سبب')"
            ),
            {
                "pid": uuid.uuid4().hex,
                "sid": stu["student_id"],
                "s": day,
                "e": day,
            },
        )
    _record(client, housing["headers"], day, [{"student_id": stu["student_id"], "status": "Absent"}])
    with SessionLocal.begin() as db:
        assert _absence_count(db, stu["student_id"]) == 0


def test_authorization_and_own_ledger(client, actors):
    student = actors(R.student)
    other = actors(R.student)
    maintenance = actors(R.maintenance_officer)
    housing = actors(R.housing_administration)
    day = TODAY
    # Non-Housing roles cannot record.
    _record(client, maintenance["headers"], day, [{"student_id": student["student_id"], "status": "Present"}], expect=403)
    _record(client, student["headers"], day, [{"student_id": student["student_id"], "status": "Present"}], expect=403)
    _record(client, housing["headers"], day, [{"student_id": student["student_id"], "status": "Late"}])
    # Student reads only their own ledger; that row is visible.
    resp = client.get("/api/v1/attendance/my-ledger", headers=student["headers"])
    assert resp.status_code == 200, resp.text
    mine = [i for i in resp.json()["items"] if i["student_id"] == student["student_id"]]
    assert mine and mine[0]["status"] == "Late"
    # Other student's ledger never contains it.
    resp2 = client.get("/api/v1/attendance/my-ledger", headers=other["headers"])
    assert resp2.status_code == 200
    assert all(i["student_id"] != student["student_id"] for i in resp2.json()["items"])
    # Officer can list the day's records.
    resp3 = client.get(
        "/api/v1/attendance/daily",
        headers=housing["headers"],
        params={"record_date": day.isoformat()},
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["total"] >= 1
