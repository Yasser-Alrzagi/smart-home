"""D6 real HTTP/DB contracts: notification mailbox and event-driven delivery."""

import uuid

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import User
from app.models.enums import UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Products-D6-Test-Password-2026!"


@pytest.fixture(scope="module", autouse=True)
def _clean_d6_tables():
    with SessionLocal.begin() as db:
        db.execute(text("DELETE FROM notifications"))
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
        name = "d6_" + uuid.uuid4().hex
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
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": name, "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        return {
            "id": u.user_id,
            "username": name,
            "headers": {"Authorization": "Bearer " + login.json()["access_token"]},
        }

    return create


def make_student(client, actors):
    student = actors()
    profile = client.post(
        "/api/v1/students/me",
        headers=student["headers"],
        json={
            "full_name": "طالب إشعارات تجريبي",
            "university": "جامعة الاختبار",
            "major": "نظم المعلومات",
        },
    )
    assert profile.status_code == 201, profile.text
    return student, profile.json()["student_id"]


def unread(client, headers):
    r = client.get("/api/v1/notifications/unread-count", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["unread"]


def mailbox(client, headers, **kw):
    r = client.get("/api/v1/notifications/my", headers=headers, params=kw)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Services: registration reaches both the student and the owning officer role
# ---------------------------------------------------------------------------


def test_registration_notifications_flow(client, actors):
    officer = actors(R.activity_officer)
    student, _ = make_student(client, actors)

    srv = client.post(
        "/api/v1/services",
        headers=officer["headers"],
        json={"service_type": "Activity", "name": "نادي الإشعارات", "is_active": True},
    )
    assert srv.status_code == 201, srv.text
    period = client.post(
        "/api/v1/service-periods",
        headers=officer["headers"],
        json={
            "service_id": srv.json()["service_id"],
            "start_date": "2026-10-01",
            "end_date": "2026-12-31",
            "capacity": 10,
        },
    )
    assert period.status_code == 201, period.text
    pid = period.json()["period_id"]
    opened = client.post(
        f"/api/v1/service-periods/{pid}/status",
        headers=officer["headers"],
        json={"status": "Open"},
    )
    assert opened.status_code == 200

    reg = client.post(
        "/api/v1/service-registrations",
        headers=student["headers"],
        json={"period_id": pid},
    )
    assert reg.status_code == 201, reg.text

    # student got the confirmation, officer got the new-registration alert
    assert unread(client, student["headers"]) >= 1
    assert unread(client, officer["headers"]) >= 1
    student_box = mailbox(client, student["headers"])
    assert any("تم تسجيلك" in n["title"] for n in student_box["items"])
    officer_box = mailbox(client, officer["headers"])
    assert any("تسجيل جديد" in n["title"] for n in officer_box["items"])

    first_id = student_box["items"][0]["notification_id"]
    mark = client.post(
        f"/api/v1/notifications/{first_id}/read", headers=student["headers"]
    )
    assert mark.status_code == 200 and mark.json()["status"] == "Read"

    # reading someone else's notification must not reveal existence
    foreign = client.post(
        f"/api/v1/notifications/{first_id}/read", headers=officer["headers"]
    )
    assert foreign.status_code == 404

    all_read = client.post("/api/v1/notifications/read-all", headers=student["headers"])
    assert all_read.status_code == 200
    assert unread(client, student["headers"]) == 0


# ---------------------------------------------------------------------------
# Complaints: Housing gets the report, the student gets the resolution
# ---------------------------------------------------------------------------


def test_complaint_notifications(client, actors):
    housing = actors(R.housing_administration)
    student, _ = make_student(client, actors)

    created = client.post(
        "/api/v1/complaints",
        headers=student["headers"],
        json={"category": "سكني", "description": "مشكلة في التكييف"},
    )
    assert created.status_code == 201, created.text
    cid = created.json()["complaint_id"]

    assert unread(client, housing["headers"]) >= 1
    assert any(
        "شكوى جديدة" in n["title"]
        for n in mailbox(client, housing["headers"])["items"]
    )

    started = client.post(
        f"/api/v1/complaints/{cid}/action",
        headers=housing["headers"],
        json={"action": "start"},
    )
    assert started.status_code == 200
    # no student notification yet (still under review; follow-up at resolve)
    resolved = client.post(
        f"/api/v1/complaints/{cid}/action",
        headers=housing["headers"],
        json={"action": "resolve", "resolution": "تمت معالجة التكييف"},
    )
    assert resolved.status_code == 200
    assert unread(client, student["headers"]) >= 1
    assert any(
        "تحديث شكواك" in n["title"] for n in mailbox(client, student["headers"])["items"]
    )


# ---------------------------------------------------------------------------
# Maintenance: officer alerted on creation, student on each status move
# ---------------------------------------------------------------------------


def test_maintenance_notifications(client, actors):
    maint = actors(R.maintenance_officer)
    student, _ = make_student(client, actors)

    created = client.post(
        "/api/v1/maintenance",
        headers=student["headers"],
        json={"problem_type": "كهرباء", "description": "الإنارة لا تعمل"},
    )
    assert created.status_code == 201, created.text
    mid = created.json()["request_id"]

    assert unread(client, maint["headers"]) >= 1
    assert any(
        "طلب صيانة جديد" in n["title"] for n in mailbox(client, maint["headers"])["items"]
    )

    assigned = client.post(
        f"/api/v1/maintenance/{mid}/action",
        headers=maint["headers"],
        json={"action": "assign"},
    )
    assert assigned.status_code == 200
    assert unread(client, student["headers"]) >= 1
    assert any(
        "تحديث طلب الصيانة" in n["title"]
        for n in mailbox(client, student["headers"])["items"]
    )


# ---------------------------------------------------------------------------
# Permissions and emergencies: Student Affairs is alerted; the student is
# notified of the decision and of the verified exit
# ---------------------------------------------------------------------------


def test_permission_and_emergency_notifications(client, actors):
    affairs = actors(R.student_affairs)
    student, _ = make_student(client, actors)

    perm = client.post(
        "/api/v1/permissions",
        headers=student["headers"],
        json={"start_date": "2026-10-05", "end_date": "2026-10-06", "reason": "ظرف عائلي"},
    )
    assert perm.status_code == 201, perm.text
    assert unread(client, affairs["headers"]) >= 1
    assert any(
        "طلب إذن غياب جديد" in n["title"]
        for n in mailbox(client, affairs["headers"])["items"]
    )

    decision = client.post(
        f"/api/v1/permissions/{perm.json()['permission_id']}/decision",
        headers=affairs["headers"],
        json={"action": "approve"},
    )
    assert decision.status_code == 200
    assert unread(client, student["headers"]) >= 1
    assert any(
        "قرار طلب الإذن" in n["title"] for n in mailbox(client, student["headers"])["items"]
    )

    report = client.post(
        "/api/v1/emergency",
        headers=student["headers"],
        json={"description": "حالة طارئة تستدعي الخروج"},
    )
    assert report.status_code == 201, report.text
    assert unread(client, affairs["headers"]) >= 2
    rid = report.json()["report_id"]

    started = client.post(
        f"/api/v1/emergency/{rid}/action", headers=affairs["headers"], json={"action": "start"}
    )
    assert started.status_code == 200
    verified = client.post(
        f"/api/v1/emergency/{rid}/action", headers=affairs["headers"], json={"action": "verify"}
    )
    assert verified.status_code == 200
    assert unread(client, student["headers"]) >= 2
    assert any(
        "تحديث البلاغ الطارئ" in n["title"]
        for n in mailbox(client, student["headers"])["items"]
    )
