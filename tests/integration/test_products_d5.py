"""D5 real HTTP/DB contracts: services, complaints, maintenance, attendance."""

from concurrent.futures import ThreadPoolExecutor
import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import AuditEvent, StudentAbsence, User
from app.models.enums import UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Products-D5-Test-Password-2026!"


@pytest.fixture(scope="module", autouse=True)
def _clean_d5_tables():
    """D5 tests use fixed service names; start from an empty product catalog."""
    from sqlalchemy import text

    with SessionLocal.begin() as db:
        db.execute(text("DELETE FROM service_registrations"))
        db.execute(text("DELETE FROM service_periods"))
        db.execute(text("DELETE FROM services"))
        db.execute(text("DELETE FROM complaints"))
        db.execute(text("DELETE FROM maintenance_requests"))
        db.execute(text("DELETE FROM permission_requests"))
        db.execute(text("DELETE FROM emergency_reports"))
        db.execute(text("DELETE FROM student_absences"))
        db.execute(text("DELETE FROM audit_events"))
        db.execute(text("DELETE FROM auth_sessions"))
        db.execute(text("DELETE FROM users"))
    yield


@pytest.fixture
def actors(client):
    def create(role=R.student, must_change=False):
        name = "d5_" + uuid.uuid4().hex
        with SessionLocal.begin() as db:
            u = User(
                username=name,
                email=name + "@example.com",
                role=role,
                is_active=True,
                password_hash=get_password_hash(PASSWORD),
                must_change_password=must_change,
            )
            db.add(u)
            db.flush()
            uid = u.user_id
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": name, "password": PASSWORD},
        )
        assert login.status_code == 200
        return {
            "id": uid,
            "headers": {"Authorization": "Bearer " + login.json()["access_token"]},
        }

    return create


def make_student(client, actors, full_name="طالب خدمات تجريبي"):
    student = actors()
    profile = client.post(
        "/api/v1/students/me",
        headers=student["headers"],
        json={
            "full_name": full_name,
            "university": "جامعة الاختبار",
            "major": "نظم المعلومات",
        },
    )
    assert profile.status_code == 201, profile.text
    return student, profile.json()["student_id"]


# ---------------------------------------------------------------------------
# Facilities: services, periods, registrations
# ---------------------------------------------------------------------------


def test_facilities_full_lifecycle(client, actors):
    officer = actors(R.activity_officer)
    other = actors(R.food_officer)

    service = client.post(
        "/api/v1/services",
        headers=officer["headers"],
        json={"service_type": "Activity", "name": "نادي البرمجة", "is_active": True},
    )
    assert service.status_code == 201, service.text
    service_id = service.json()["service_id"]

    # wrong remit for the service type
    wrong = client.post(
        "/api/v1/services",
        headers=officer["headers"],
        json={"service_type": "Food", "name": "مطعم", "is_active": True},
    )
    assert wrong.status_code == 422

    duplicate = client.post(
        "/api/v1/services",
        headers=officer["headers"],
        json={"service_type": "Activity", "name": "نادي البرمجة", "is_active": True},
    )
    assert duplicate.status_code == 409

    # another officer cannot manage this service
    foreign = client.patch(
        f"/api/v1/services/{service_id}",
        headers=other["headers"],
        json={"is_active": False},
    )
    assert foreign.status_code == 403

    period = client.post(
        "/api/v1/service-periods",
        headers=officer["headers"],
        json={
            "service_id": service_id,
            "start_date": "2026-10-01",
            "end_date": "2026-12-31",
            "capacity": 1,
        },
    )
    assert period.status_code == 201, period.text
    period_id = period.json()["period_id"]

    # registering before opening is refused
    student, _ = make_student(client, actors)
    early = client.post(
        "/api/v1/service-registrations",
        headers=student["headers"],
        json={"period_id": period_id},
    )
    assert early.status_code == 409

    opened = client.post(
        f"/api/v1/service-periods/{period_id}/status",
        headers=officer["headers"],
        json={"status": "Open"},
    )
    assert opened.status_code == 200 and opened.json()["status"] == "Open"

    other_student, _ = make_student(client, actors)

    first = client.post(
        "/api/v1/service-registrations",
        headers=student["headers"],
        json={"period_id": period_id},
    )
    assert first.status_code == 201, first.text
    registration_id = first.json()["registration_id"]

    duplicate_reg = client.post(
        "/api/v1/service-registrations",
        headers=student["headers"],
        json={"period_id": period_id},
    )
    assert duplicate_reg.status_code == 409

    over_capacity = client.post(
        "/api/v1/service-registrations",
        headers=other_student["headers"],
        json={"period_id": period_id},
    )
    assert over_capacity.status_code == 422

    mine = client.get(
        "/api/v1/service-registrations/me", headers=student["headers"]
    )
    assert mine.status_code == 200 and len(mine.json()) == 1

    # officer sees the registration list
    listing = client.get(
        f"/api/v1/service-periods/{period_id}/registrations",
        headers=officer["headers"],
    )
    assert listing.status_code == 200 and listing.json()["total"] == 1

    # cancel frees the seat
    cancelled = client.post(
        f"/api/v1/service-registrations/{registration_id}/cancel",
        headers=student["headers"],
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "Cancelled"

    seat_freed = client.post(
        "/api/v1/service-registrations",
        headers=other_student["headers"],
        json={"period_id": period_id},
    )
    assert seat_freed.status_code == 201

    # closing refuses new registrations but keeps history
    closed = client.post(
        f"/api/v1/service-periods/{period_id}/status",
        headers=officer["headers"],
        json={"status": "Closed"},
    )
    assert closed.status_code == 200
    late = client.post(
        "/api/v1/service-registrations",
        headers=student["headers"],
        json={"period_id": period_id},
    )
    assert late.status_code == 409

    forbidden = client.post(
        f"/api/v1/service-periods/{period_id}/status",
        headers=officer["headers"],
        json={"status": "Upcoming"},
    )
    assert forbidden.status_code == 409


def test_facilities_concurrent_capacity(client, actors):
    officer = actors(R.sports_officer)
    service = client.post(
        "/api/v1/services",
        headers=officer["headers"],
        json={"service_type": "Sports", "name": "كرة الطائرة", "is_active": True},
    ).json()
    period = client.post(
        "/api/v1/service-periods",
        headers=officer["headers"],
        json={
            "service_id": service["service_id"],
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "capacity": 1,
        },
    ).json()
    client.post(
        f"/api/v1/service-periods/{period['period_id']}/status",
        headers=officer["headers"],
        json={"status": "Open"},
    )
    students = [make_student(client, actors)[0] for _ in range(2)]

    def attempt(student):
        return client.post(
            "/api/v1/service-registrations",
            headers=student["headers"],
            json={"period_id": period["period_id"]},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(attempt, students))

    assert results.count(201) == 1, results
    with SessionLocal.begin() as db:
        from app.models import ServiceRegistration
        from app.models.enums import ServiceRegistrationStatus as SR

        active = db.scalar(
            select(func.count(ServiceRegistration.registration_id)).where(
                ServiceRegistration.status == SR.registered
            )
        )
    assert active == 1


def test_facilities_role_guardrails(client, actors):
    for role in [R.student, R.student_affairs, R.housing_administration, R.maintenance_officer, R.system_administrator]:
        user = actors(role)
        response = client.get("/api/v1/services", headers=user["headers"])
        assert response.status_code == 403, role
    blocked = actors(R.food_officer, must_change=True)
    assert (
        client.get("/api/v1/services", headers=blocked["headers"]).status_code == 403
    )
    # a student without a profile can still browse active periods (public catalog)
    anonymous = actors()
    assert (
        client.get("/api/v1/service-periods", headers=anonymous["headers"]).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# Complaints & maintenance
# ---------------------------------------------------------------------------


def test_complaint_lifecycle(client, actors):
    student, student_id = make_student(client, actors, "شاكٍ تجريبي")
    ha = actors(R.housing_administration)
    officer = actors(R.maintenance_officer)

    complaint = client.post(
        "/api/v1/complaints",
        headers=student["headers"],
        json={"category": "النظافة", "description": "نظافة الممر غير كافية"},
    )
    assert complaint.status_code == 201, complaint.text
    complaint_id = complaint.json()["complaint_id"]

    # an officer of another remit cannot act
    foreign = client.post(
        f"/api/v1/complaints/{complaint_id}/action",
        headers=officer["headers"],
        json={"action": "start", "resolution": None},
    )
    assert foreign.status_code == 403

    started = client.post(
        f"/api/v1/complaints/{complaint_id}/action",
        headers=ha["headers"],
        json={"action": "start"},
    )
    assert started.status_code == 200 and started.json()["status"] == "Under Review"

    no_resolution = client.post(
        f"/api/v1/complaints/{complaint_id}/action",
        headers=ha["headers"],
        json={"action": "resolve"},
    )
    assert no_resolution.status_code == 422

    resolved = client.post(
        f"/api/v1/complaints/{complaint_id}/action",
        headers=ha["headers"],
        json={"action": "resolve", "resolution": "تمت جدولة تنظيف إضافي"},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "Resolved"

    closed = client.post(
        f"/api/v1/complaints/{complaint_id}/action",
        headers=ha["headers"],
        json={"action": "close", "resolution": "تمت الجدولة"},
    )
    assert closed.status_code == 200 and closed.json()["status"] == "Closed"

    invalid = client.post(
        f"/api/v1/complaints/{complaint_id}/action",
        headers=ha["headers"],
        json={"action": "start"},
    )
    assert invalid.status_code == 409

    mine = client.get("/api/v1/complaints/my", headers=student["headers"])
    assert mine.status_code == 200 and mine.json()["total"] == 1
    other, _ = make_student(client, actors, "طالب آخر")
    assert client.get("/api/v1/complaints/my", headers=other["headers"]).json()["total"] == 0
    assert client.get("/api/v1/complaints", headers=student["headers"]).status_code == 403


def test_maintenance_lifecycle_with_room_check(client, actors, structure_fixture=None):
    student, student_id = make_student(client, actors, "مقدم طلب صيانة")
    officer = actors(R.maintenance_officer)

    # attaching a room the student does not occupy is refused
    wrong_room = client.post(
        "/api/v1/maintenance",
        headers=student["headers"],
        json={
            "room_id": str(uuid.uuid4()),
            "problem_type": "سباكة",
            "description": "تسرب ماء من السقف",
        },
    )
    assert wrong_room.status_code == 422

    request = client.post(
        "/api/v1/maintenance",
        headers=student["headers"],
        json={"problem_type": "كهرباء", "description": "المصباح لا يعمل"},
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["request_id"]

    assigned = client.post(
        f"/api/v1/maintenance/{request_id}/action",
        headers=officer["headers"],
        json={"action": "assign"},
    )
    assert assigned.status_code == 200 and assigned.json()["status"] == "Assigned"

    in_progress = client.post(
        f"/api/v1/maintenance/{request_id}/action",
        headers=officer["headers"],
        json={"action": "progress"},
    )
    assert in_progress.status_code == 200

    resolved = client.post(
        f"/api/v1/maintenance/{request_id}/action",
        headers=officer["headers"],
        json={"action": "resolve", "resolution": "تم استبدال المصباح"},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "Resolved"

    closed = client.post(
        f"/api/v1/maintenance/{request_id}/action",
        headers=officer["headers"],
        json={"action": "close", "resolution": "تم الاستبدال"},
    )
    assert closed.status_code == 200

    mine = client.get("/api/v1/maintenance/my", headers=student["headers"])
    assert mine.status_code == 200 and mine.json()["total"] == 1

    foreign = client.post(
        f"/api/v1/maintenance/{request_id}/action",
        headers=actors(R.housing_administration)["headers"],
        json={"action": "assign"},
    )
    assert foreign.status_code == 403


# ---------------------------------------------------------------------------
# Permissions / emergency / absences
# ---------------------------------------------------------------------------


def test_permission_approval_creates_absence(client, actors):
    student, student_id = make_student(client, actors, "مسافر تجريبي")
    affairs = actors(R.student_affairs)

    permission = client.post(
        "/api/v1/permissions",
        headers=student["headers"],
        json={
            "start_date": "2026-11-02",
            "end_date": "2026-11-05",
            "reason": "زيارة عائلية في محافظة أخرى",
        },
    )
    assert permission.status_code == 201, permission.text
    permission_id = permission.json()["permission_id"]

    listings = client.get("/api/v1/permissions", headers=affairs["headers"]).json()
    assert listings["total"] == 1

    approved = client.post(
        f"/api/v1/permissions/{permission_id}/decision",
        headers=affairs["headers"],
        json={"action": "approve"},
    )
    assert approved.status_code == 200 and approved.json()["status"] == "Approved"

    with SessionLocal.begin() as db:
        absence = db.scalar(
            select(StudentAbsence).where(
                StudentAbsence.student_id == student_id,
                StudentAbsence.absence_type == "permission",
            )
        )
    assert absence is not None and absence.source == f"permission:{permission_id}"

    again = client.post(
        f"/api/v1/permissions/{permission_id}/decision",
        headers=affairs["headers"],
        json={"action": "approve"},
    )
    assert again.status_code == 409

    mine = client.get("/api/v1/absences/my", headers=student["headers"])
    assert mine.status_code == 200 and mine.json()["total"] == 1
    assert mine.json()["items"][0]["absence_type"] == "Permission"


def test_permission_cancel_and_reject(client, actors):
    student, _ = make_student(client, actors)
    affairs = actors(R.student_affairs)

    pending = client.post(
        "/api/v1/permissions",
        headers=student["headers"],
        json={
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "reason": "موعد طبي",
        },
    ).json()

    cancelled = client.post(
        f"/api/v1/permissions/{pending['permission_id']}/cancel",
        headers=student["headers"],
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "Cancelled"

    second = client.post(
        "/api/v1/permissions",
        headers=student["headers"],
        json={
            "start_date": "2026-12-10",
            "end_date": "2026-12-12",
            "reason": "موعد طبي آخر",
        },
    ).json()

    rejected = client.post(
        f"/api/v1/permissions/{second['permission_id']}/decision",
        headers=affairs["headers"],
        json={"action": "reject"},
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "Rejected"

    # reject does not create an absence
    with SessionLocal.begin() as db:
        count = db.scalar(
            select(func.count(StudentAbsence.absence_id)).where(
                StudentAbsence.absence_type == "permission"
            )
        )
    assert count == 0


def test_emergency_verification_creates_absence(client, actors):
    student, student_id = make_student(client, actors, "مبلّغ تجريبي")
    affairs = actors(R.student_affairs)

    report = client.post(
        "/api/v1/emergency",
        headers=student["headers"],
        json={"description": "حالة صحية طارئة تتطلب مغادرة السكن"},
    )
    assert report.status_code == 201, report.text
    report_id = report.json()["report_id"]
    assert report.json()["exit_verified"] is False
    assert report.json()["absence_id"] is None

    # absence must NOT exist before verification (rule 9.2)
    with SessionLocal.begin() as db:
        before = db.scalar(
            select(func.count(StudentAbsence.absence_id)).where(
                StudentAbsence.absence_type == "emergency"
            )
        )
    assert before == 0

    started = client.post(
        f"/api/v1/emergency/{report_id}/action",
        headers=affairs["headers"],
        json={"action": "start"},
    )
    assert started.status_code == 200 and started.json()["status"] == "Under Review"

    verified = client.post(
        f"/api/v1/emergency/{report_id}/action",
        headers=affairs["headers"],
        json={"action": "verify"},
    )
    assert verified.status_code == 200
    body = verified.json()
    assert body["exit_verified"] is True and body["absence_id"] is not None

    closed = client.post(
        f"/api/v1/emergency/{report_id}/action",
        headers=affairs["headers"],
        json={"action": "close"},
    )
    assert closed.status_code == 200 and closed.json()["status"] == "Closed"

    listing = client.get("/api/v1/absences", headers=affairs["headers"])
    assert listing.status_code == 200
    assert listing.json()["items"][0]["absence_type"] == "Emergency"

    foreign = client.post(
        f"/api/v1/emergency/{report_id}/action",
        headers=actors(R.housing_administration)["headers"],
        json={"action": "start"},
    )
    assert foreign.status_code == 403


def test_attendance_audit_trail(client, actors):
    affairs = actors(R.student_affairs)
    student, _ = make_student(client, actors)
    permission = client.post(
        "/api/v1/permissions",
        headers=student["headers"],
        json={
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "reason": "مناسبة عائلية",
        },
    ).json()
    decision = client.post(
        f"/api/v1/permissions/{permission['permission_id']}/decision",
        headers=affairs["headers"],
        json={"action": "approve"},
    )
    assert decision.status_code == 200
    with SessionLocal.begin() as db:
        actions = set(
            db.scalars(
                select(AuditEvent.action).where(AuditEvent.actor_id == affairs["id"])
            )
        )
    # only attendance actions are within Student Affairs remit in this test
    assert {"permission.update"} <= actions
    assert not ({"service.create", "complaint.update", "maintenance.update", "housing.allocate"} & actions)
