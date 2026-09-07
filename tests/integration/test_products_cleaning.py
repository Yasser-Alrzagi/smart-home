"""D9 real HTTP/DB contracts: cleaning cycles, BFS/A* runs, approval, execution."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import Student, User
from app.models.enums import AcademicStatus, HousingStatus, UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Products-D9-Test-Password-2026!"
START = (date.today() + timedelta(days=2)).isoformat()
END = (date.today() + timedelta(days=4)).isoformat()


@pytest.fixture(scope="module", autouse=True)
def _clean_d9_tables():
    with SessionLocal.begin() as db:
        for t in (
            "notifications", "cleaning_assignments", "cleaning_cycles",
            "ai_optimization_runs", "room_assignments", "rooms", "apartments",
            "floors", "students", "auth_sessions", "audit_events", "users",
        ):
            db.execute(text(f"DELETE FROM {t}"))
    yield


@pytest.fixture
def actors(client):
    def create(role=R.student):
        name = "d9_" + uuid.uuid4().hex
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
                    full_name="طالب نظافة " + uuid.uuid4().hex[:4],
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


@pytest.fixture
def structure():
    """Main floor with 4 rooms across 2 apartments + one empty floor."""
    tag = uuid.uuid4().hex[:8]
    floor_a = "d9fa-" + uuid.uuid4().hex[:24]
    floor_b = "d9fb-" + uuid.uuid4().hex[:24]
    with SessionLocal.begin() as db:
        db.execute(
            text("INSERT INTO floors (floor_id, building_name, floor_number) VALUES (:a,:bn,'1'),(:b,:bn,'2')"),
            {"a": floor_a, "b": floor_b, "bn": "مبنى د9 " + tag},
        )
        apartment = "d9ap-" + uuid.uuid4().hex[:24]
        db.execute(
            text("INSERT INTO apartments (apartment_id, floor_id, apartment_number) VALUES (:ap,:a,'101')"),
            {"ap": apartment, "a": floor_a},
        )
        rooms = ["d9r-%s" % uuid.uuid4().hex[:20] for _ in range(4)]
        for i, room in enumerate(rooms):
            db.execute(
                text("INSERT INTO rooms (room_id, apartment_id, room_number, capacity, status) VALUES (:r,:ap,:n,2,'available')"),
                {"r": room, "ap": apartment, "n": str(101 + i)},
            )
    return {"floor_a": floor_a, "floor_b": floor_b, "rooms": rooms}


def _assign(db, student_id, room_id, by_user):
    db.execute(
        text("INSERT INTO room_assignments (assignment_id, student_id, room_id, assignment_date, status, assigned_by) "
             "VALUES (:id,:sid,:rid,NOW(),'active',:by)"),
        {"id": "d9as-" + uuid.uuid4().hex[:24], "sid": student_id, "rid": room_id, "by": by_user},
    )


def _notifications_count(db, user_id):
    return db.execute(
        text("SELECT COUNT(*) FROM notifications WHERE user_id=:uid AND title='مهمة نظافة جديدة'"),
        {"uid": user_id},
    ).scalar()


def test_full_cycle_bfs_and_astar(client, actors, structure):
    officer = actors(R.cleaning_officer)
    s1 = actors(R.student)
    s2 = actors(R.student)
    s3 = actors(R.student)
    s4 = actors(R.student)
    with SessionLocal.begin() as db:
        for i, s in enumerate([s1, s2, s3, s4]):
            _assign(db, s["student_id"], structure["rooms"][i], officer["id"])

    # floors picker
    resp = client.get("/api/v1/cleaning/floors", headers=officer["headers"])
    assert resp.status_code == 200 and any(f["floor_id"] == structure["floor_a"] for f in resp.json())

    # create cycle (3 days × 4 rooms = 12 tasks)
    resp = client.post(
        "/api/v1/cleaning/cycles",
        headers=officer["headers"],
        json={"floor_id": structure["floor_a"], "start_date": START, "end_date": END},
    )
    assert resp.status_code == 201, resp.text
    cycle_id = resp.json()["cycle_id"]
    assert resp.json()["status"] == "Draft"

    # run BFS and A*
    bfs = client.post(
        "/api/v1/cleaning/cycles/" + cycle_id + "/optimize",
        headers=officer["headers"],
        json={"algorithm": "BFS"},
    )
    assert bfs.status_code == 201, bfs.text
    assert bfs.json()["feasibility_rate"] == 1.0
    assert bfs.json()["task_count"] == 12
    astar = client.post(
        "/api/v1/cleaning/cycles/" + cycle_id + "/optimize",
        headers=officer["headers"],
        json={"algorithm": "A*"},
    )
    assert astar.status_code == 201, astar.text
    assert astar.json()["total_cost"] <= bfs.json()["total_cost"]

    # detail: two runs, no assignments yet
    detail = client.get("/api/v1/cleaning/cycles/" + cycle_id, headers=officer["headers"])
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["runs"]) == 2 and body["assignments"] == []
    assert body["status"] == "Optimizing"

    # approve the BFS run → assignments materialized
    approved = client.post(
        "/api/v1/cleaning/cycles/" + cycle_id + "/approve",
        headers=officer["headers"],
        json={"run_id": bfs.json()["run_id"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "Approved"
    assert approved.json()["assignments_count"] == 12

    # activate → students notified
    active = client.post(
        "/api/v1/cleaning/cycles/" + cycle_id + "/activate",
        headers=officer["headers"],
    )
    assert active.status_code == 200 and active.json()["status"] == "Active"
    with SessionLocal.begin() as db:
        assert _notifications_count(db, s1["id"]) == 1
        assert _notifications_count(db, s2["id"]) == 1

    # student sees own tasks, starts and completes one
    mine = client.get("/api/v1/cleaning/my", headers=s1["headers"])
    assert mine.status_code == 200 and mine.json()["total"] >= 1
    first = mine.json()["items"][0]
    assert first["status"] == "Pending"
    started = client.post(
        "/api/v1/cleaning/my/" + first["assignment_id"],
        headers=s1["headers"],
        json={"action": "start"},
    )
    assert started.status_code == 200 and started.json()["status"] == "In Progress"
    done = client.post(
        "/api/v1/cleaning/my/" + first["assignment_id"],
        headers=s1["headers"],
        json={"action": "complete"},
    )
    assert done.status_code == 200 and done.json()["status"] == "Completed"
    assert done.json()["completed_date"] is not None
    # repeating complete → 409
    again = client.post(
        "/api/v1/cleaning/my/" + first["assignment_id"],
        headers=s1["headers"],
        json={"action": "complete"},
    )
    assert again.status_code == 409

    # officer skips another student's pending task
    mine2 = client.get("/api/v1/cleaning/my", headers=s2["headers"]).json()["items"]
    skipped = client.post(
        "/api/v1/cleaning/assignments/" + mine2[0]["assignment_id"] + "/skip",
        headers=officer["headers"],
    )
    assert skipped.status_code == 200 and skipped.json()["status"] == "Skipped"

    # complete the cycle; further optimization is refused
    done_cycle = client.post(
        "/api/v1/cleaning/cycles/" + cycle_id + "/complete",
        headers=officer["headers"],
    )
    assert done_cycle.status_code == 200 and done_cycle.json()["status"] == "Completed"
    refused = client.post(
        "/api/v1/cleaning/cycles/" + cycle_id + "/optimize",
        headers=officer["headers"],
        json={"algorithm": "BFS"},
    )
    assert refused.status_code == 409


def test_guards_and_feasibility(client, actors, structure):
    officer = actors(R.cleaning_officer)
    student = actors(R.student)
    maintenance = actors(R.maintenance_officer)
    other = actors(R.student)
    with SessionLocal.begin() as db:
        _assign(db, student["student_id"], structure["rooms"][0], officer["id"])
        _assign(db, other["student_id"], structure["rooms"][1], officer["id"])

    # student cannot create a cycle
    resp = client.post(
        "/api/v1/cleaning/cycles",
        headers=student["headers"],
        json={"floor_id": structure["floor_a"], "start_date": START, "end_date": END},
    )
    assert resp.status_code == 403
    # maintenance officer cannot optimize
    resp = client.post(
        "/api/v1/cleaning/cycles/" + "x" * 36 + "/optimize",
        headers=maintenance["headers"],
        json={"algorithm": "BFS"},
    )
    assert resp.status_code == 403

    # floor with no residents → infeasible at optimize time
    resp = client.post(
        "/api/v1/cleaning/cycles",
        headers=officer["headers"],
        json={"floor_id": structure["floor_b"], "start_date": START, "end_date": END},
    )
    assert resp.status_code == 201
    empty_cycle = resp.json()["cycle_id"]
    resp = client.post(
        "/api/v1/cleaning/cycles/" + empty_cycle + "/optimize",
        headers=officer["headers"],
        json={"algorithm": "BFS"},
    )
    assert resp.status_code == 422

    # student cannot skip; cross-student update → 404
    assert client.get("/api/v1/cleaning/my", headers=student["headers"]).json()["items"] == []
    other_mine = client.get("/api/v1/cleaning/my", headers=other["headers"]).json()["items"]
    skip_attempt = client.post(
        "/api/v1/cleaning/assignments/" + "x" * 36 + "/skip",
        headers=student["headers"],
    )
    assert skip_attempt.status_code == 403
    assert other_mine == []
