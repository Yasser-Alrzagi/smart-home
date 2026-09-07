"""D4 real HTTP/DB contracts: structure, allocation, transfers, capacity.

Uses the same two-stage admission flow as D3 to produce accepted students,
then exercises the housing product end to end on the real database.
"""

from concurrent.futures import ThreadPoolExecutor
import io
import uuid

from PIL import Image
import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models import (
    AuditEvent,
    RoomAssignment,
    StudentStatusHistory,
    User,
)
from app.models.enums import RoomAssignmentStatus as A
from app.models.enums import UserRole as R

pytestmark = pytest.mark.db
PASSWORD = "Housing-Test-Password-2026!"


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), "#e0ede3").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def actors(client):
    def create(role=R.student, must_change=False):
        name = "d4_" + uuid.uuid4().hex
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


@pytest.fixture
def structure(client, actors):
    """Officer + a fresh floor/apartment/room; returns accessor helpers."""
    ha = actors(R.housing_administration)
    tag = uuid.uuid4().hex[:8]

    def add_floor(building=None, number=None):
        return client.post(
            "/api/v1/housing/floors",
            headers=ha["headers"],
            json={
                "building_name": building or ("بناء " + tag),
                "floor_number": number or "1",
            },
        )

    def add_apartment(floor_id, number=None):
        return client.post(
            "/api/v1/housing/apartments",
            headers=ha["headers"],
            json={
                "floor_id": floor_id,
                "apartment_number": number or ("شقة " + tag),
            },
        )

    def add_room(apartment_id, number=None, capacity=1):
        return client.post(
            "/api/v1/housing/rooms",
            headers=ha["headers"],
            json={
                "apartment_id": apartment_id,
                "room_number": number or ("غرفة " + tag),
                "capacity": capacity,
            },
        )

    floor = add_floor()
    assert floor.status_code == 201, floor.text
    apartment = add_apartment(floor.json()["floor_id"])
    assert apartment.status_code == 201, apartment.text
    room = add_room(apartment.json()["apartment_id"])
    assert room.status_code == 201, room.text
    return {
        "ha": ha,
        "tag": tag,
        "floor": floor.json(),
        "apartment": apartment.json(),
        "room": room.json(),
        "add_floor": add_floor,
        "add_apartment": add_apartment,
        "add_room": add_room,
    }


def accepted_student(client, actors, sa=None, ha=None):
    """Run the full D3 flow; returns the finished account and application."""
    owner = actors()
    profile = client.post(
        "/api/v1/students/me",
        headers=owner["headers"],
        json={
            "full_name": "طالب سكن تجريبي",
            "university": "جامعة الاختبار",
            "major": "علوم الحاسوب",
        },
    )
    assert profile.status_code == 201, profile.text
    student_id = profile.json()["student_id"]
    application = client.post(
        "/api/v1/applications", headers=owner["headers"]
    ).json()
    for kind in ["National ID", "Enrollment Certificate"]:
        response = client.post(
            f"/api/v1/applications/{application['application_id']}/documents",
            headers=owner["headers"],
            data={"document_type": kind, "expected_version": application["version"]},
            files={"file": ("id.png", png_bytes(), "image/png")},
        )
        assert response.status_code == 200, response.text
        application = response.json()
    response = client.post(
        f"/api/v1/applications/{application['application_id']}/submit",
        headers=owner["headers"],
        json={"expected_version": application["version"]},
    )
    assert response.status_code == 200, response.text
    application = response.json()
    sa = sa or actors(R.student_affairs)
    ha = ha or actors(R.housing_administration)
    for action in ["start", "complete", "accept"]:
        response = client.post(
            f"/api/v1/applications/{application['application_id']}/review",
            headers=(sa if action in {"start", "complete"} else ha)["headers"],
            json={
                "expected_version": application["version"],
                "action": action,
                "note": "تم التحقق من المستندات",
                "document_types": [],
            },
        )
        assert response.status_code == 200, response.text
        application = response.json()
    assert application["status"] == "Accepted"
    return {
        "student": owner,
        "user_id": owner["id"],
        "student_id": student_id,
        "application": application,
        "sa": sa,
        "ha": ha,
    }


def allocate(client, ha, student_id, room_id):
    return client.post(
        "/api/v1/housing/assignments",
        headers=ha["headers"],
        json={"student_id": student_id, "room_id": room_id},
    )


def transfer(client, ha, assignment_id, to_room_id):
    return client.post(
        f"/api/v1/housing/assignments/{assignment_id}/transfer",
        headers=ha["headers"],
        json={"to_room_id": to_room_id},
    )


def end(client, ha, assignment_id):
    return client.post(
        f"/api/v1/housing/assignments/{assignment_id}/end",
        headers=ha["headers"],
    )


def my_room(client, student):
    return client.get("/api/v1/housing/me", headers=student["headers"])


# ---------------------------------------------------------------------------
# Structure management
# ---------------------------------------------------------------------------


def test_structure_creation_and_duplicates(client, structure):
    ha, tag = structure["ha"], structure["tag"]

    duplicate_floor = structure["add_floor"]()
    assert duplicate_floor.status_code == 409
    duplicate_apartment = structure["add_apartment"](structure["floor"]["floor_id"])
    assert duplicate_apartment.status_code == 409
    duplicate_room = structure["add_room"](structure["apartment"]["apartment_id"])
    assert duplicate_room.status_code == 409

    missing_apartment = client.post(
        "/api/v1/housing/rooms",
        headers=ha["headers"],
        json={
            "apartment_id": str(uuid.uuid4()),
            "room_number": "x",
            "capacity": 1,
        },
    )
    assert missing_apartment.status_code == 404

    bad_capacity = client.post(
        "/api/v1/housing/rooms",
        headers=ha["headers"],
        json={
            "apartment_id": structure["apartment"]["apartment_id"],
            "room_number": "cap-" + tag,
            "capacity": 11,
        },
    )
    assert bad_capacity.status_code == 422

    listing = client.get("/api/v1/housing/rooms", headers=ha["headers"])
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1


def test_room_update_rules(client, structure):
    ha = structure["ha"]
    room_id = structure["room"]["room_id"]

    grown = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"capacity": 4},
    )
    assert grown.status_code == 200
    assert grown.json()["capacity"] == 4

    empty = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={},
    )
    assert empty.status_code == 422

    derived = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"status": "Partially Occupied"},
    )
    assert derived.status_code == 422

    maintenance = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"status": "Maintenance"},
    )
    assert maintenance.status_code == 200
    assert maintenance.json()["status"] == "Maintenance"

    reopened = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"status": "Available"},
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "Available" and reopened.json()["occupancy"] == 0


# ---------------------------------------------------------------------------
# Allocation rules
# ---------------------------------------------------------------------------


def test_allocation_requires_accepted_application(client, actors, structure):
    ha = structure["ha"]
    owner = actors()  # profile + draft only, never accepted
    profile = client.post(
        "/api/v1/students/me",
        headers=owner["headers"],
        json={
            "full_name": "بدون قبول",
            "university": "جامعة الاختبار",
            "major": "رياضيات",
        },
    )
    assert profile.status_code == 201
    result = allocate(client, ha, profile.json()["student_id"], structure["room"]["room_id"])
    assert result.status_code == 409

    unknown = allocate(client, ha, str(uuid.uuid4()), structure["room"]["room_id"])
    assert unknown.status_code == 404


def test_allocation_moves_student_to_active(client, structure, actors):
    ha = structure["ha"]
    state = accepted_student(client, actors, ha=ha)
    student_id = state["student_id"]

    eligible = client.get("/api/v1/housing/students/unassigned", headers=ha["headers"])
    assert eligible.status_code == 200
    assert any(item["student_id"] == student_id for item in eligible.json()["items"])

    result = allocate(client, ha, student_id, structure["room"]["room_id"])
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["status"] == "Active"
    assert body["room_status"] == "Fully Occupied"
    assert body["occupancy"] == 1

    profile_after = client.get(
        "/api/v1/students/me", headers=state["student"]["headers"]
    ).json()
    assert profile_after["housing_status"] == "Active"

    with SessionLocal.begin() as db:
        history = db.scalars(
            select(StudentStatusHistory).where(
                StudentStatusHistory.student_id == student_id
            )
        ).all()
    assert [entry.new_status for entry in history] == ["Active"]
    assert history[0].status_type.value == "Housing"

    again = allocate(client, ha, student_id, structure["room"]["room_id"])
    assert again.status_code == 409

    eligible = client.get("/api/v1/housing/students/unassigned", headers=ha["headers"])
    assert not any(item["student_id"] == student_id for item in eligible.json()["items"])


def test_capacity_and_room_status_derivation(client, structure, actors):
    ha = structure["ha"]
    room_id = structure["room"]["room_id"]
    client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"capacity": 2},
    )
    first = accepted_student(client, actors, ha=ha)
    second = accepted_student(client, actors, ha=ha)
    third = accepted_student(client, actors, ha=ha)

    a1 = allocate(client, ha, first["student_id"], room_id).json()
    assert a1["status"] == "Active"
    assert a1["room_status"] == "Partially Occupied"
    assert a1["occupancy"] == 1

    a2 = allocate(client, ha, second["student_id"], room_id).json()
    assert a2["room_status"] == "Fully Occupied"
    assert a2["occupancy"] == 2

    over = allocate(client, ha, third["student_id"], room_id)
    assert over.status_code == 422

    shrink = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"capacity": 1},
    )
    assert shrink.status_code == 409

    ended = end(client, ha, a1["assignment_id"]).json()
    assert ended["room_status"] == "Partially Occupied"
    assert ended["occupancy"] == 1

    retry = allocate(client, ha, third["student_id"], room_id)
    assert retry.status_code == 201, retry.text


def test_maintenance_and_closed_refuse_allocation(client, structure, actors):
    ha = structure["ha"]
    state = accepted_student(client, actors, ha=ha)
    room_id = structure["room"]["room_id"]

    client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"status": "Maintenance"},
    )
    assert allocate(client, ha, state["student_id"], room_id).status_code == 409

    client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"status": "Available"},
    )
    assert allocate(client, ha, state["student_id"], room_id).status_code == 201

    second = accepted_student(client, actors, ha=ha)
    closed = client.patch(
        f"/api/v1/housing/rooms/{room_id}",
        headers=ha["headers"],
        json={"status": "Closed"},
    )
    assert closed.status_code == 200
    assert allocate(client, ha, second["student_id"], room_id).status_code == 409


def test_suspended_student_refused(client, structure, actors):
    ha = structure["ha"]
    state = accepted_student(client, actors, ha=ha)
    with SessionLocal.begin() as db:
        from app.models import Student

        student = db.scalar(
            select(Student).where(Student.user_id == state["user_id"])
        )
        from app.models.enums import HousingStatus

        student.housing_status = HousingStatus.suspended
    assert (
        allocate(client, ha, state["student_id"], structure["room"]["room_id"]).status_code
        == 409
    )


# ---------------------------------------------------------------------------
# Transfers and endings
# ---------------------------------------------------------------------------


def test_transfer_respects_capacity_and_history(client, structure, actors):
    ha = structure["ha"]
    room_b = structure["add_room"](
        structure["apartment"]["apartment_id"], "غرفة ب " + structure["tag"]
    ).json()
    state = accepted_student(client, actors, ha=ha)

    allocated = allocate(client, ha, state["student_id"], structure["room"]["room_id"]).json()
    moved = transfer(client, ha, allocated["assignment_id"], room_b["room_id"])
    assert moved.status_code == 201, moved.text
    body = moved.json()
    assert body["room_id"] == room_b["room_id"]
    assert body["status"] == "Active"
    assert body["room_status"] == "Fully Occupied"

    old = client.get(
        "/api/v1/housing/assignments?status=Transferred", headers=ha["headers"]
    ).json()
    assert any(
        item["assignment_id"] == allocated["assignment_id"] for item in old["items"]
    )

    listing = client.get(
        "/api/v1/housing/rooms",
        headers=ha["headers"],
        params={"building": structure["floor"]["building_name"]},
    ).json()
    rooms = {item["room_id"]: item for item in listing["items"]}
    assert rooms[structure["room"]["room_id"]]["occupancy"] == 0
    assert rooms[structure["room"]["room_id"]]["status"] == "Available"

    mine = my_room(client, state["student"])
    assert mine.status_code == 200
    assert mine.json()["room_id"] == room_b["room_id"]
    assert len(mine.json()["history"]) == 1
    assert mine.json()["history"][0]["status"] == "Transferred"


def test_transfer_conflicts(client, structure, actors):
    ha = structure["ha"]
    room_b = structure["add_room"](
        structure["apartment"]["apartment_id"], "غرفة ت " + structure["tag"]
    ).json()
    first = accepted_student(client, actors, ha=ha)
    second = accepted_student(client, actors, ha=ha)

    a1 = allocate(client, ha, first["student_id"], structure["room"]["room_id"]).json()
    occupied = allocate(client, ha, second["student_id"], room_b["room_id"])
    assert occupied.status_code == 201

    same = transfer(client, ha, a1["assignment_id"], structure["room"]["room_id"])
    assert same.status_code == 409

    full = transfer(client, ha, a1["assignment_id"], room_b["room_id"])
    assert full.status_code == 422

    client.patch(
        f"/api/v1/housing/rooms/{room_b['room_id']}",
        headers=ha["headers"],
        json={"status": "Maintenance"},
    )
    maintenance = transfer(client, ha, a1["assignment_id"], room_b["room_id"])
    assert maintenance.status_code == 409
    client.patch(
        f"/api/v1/housing/rooms/{room_b['room_id']}",
        headers=ha["headers"],
        json={"status": "Available"},
    )

    # A valid transfer needs a free target room; room_b is still occupied.
    room_c = structure["add_room"](
        structure["apartment"]["apartment_id"], "غرفة ج " + structure["tag"]
    ).json()
    moved = transfer(client, ha, a1["assignment_id"], room_c["room_id"])
    assert moved.status_code == 201
    assert moved.json()["room_id"] == room_c["room_id"]
    repeat = transfer(client, ha, a1["assignment_id"], room_c["room_id"])
    assert repeat.status_code == 409


def test_end_assignment_and_re_eligibility(client, structure, actors):
    ha = structure["ha"]
    state = accepted_student(client, actors, ha=ha)
    allocated = allocate(client, ha, state["student_id"], structure["room"]["room_id"]).json()

    ended = end(client, ha, allocated["assignment_id"])
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "Ended"

    assert my_room(client, state["student"]).status_code == 404

    eligible = client.get("/api/v1/housing/students/unassigned", headers=ha["headers"]).json()
    assert any(
        item["student_id"] == state["student_id"] for item in eligible["items"]
    )

    assert end(client, ha, allocated["assignment_id"]).status_code == 409


def test_student_sees_only_own_room(client, structure, actors):
    ha = structure["ha"]
    first = accepted_student(client, actors, ha=ha)
    second = accepted_student(client, actors, ha=ha)

    allocate(client, ha, first["student_id"], structure["room"]["room_id"])

    mine = my_room(client, first["student"])
    assert mine.status_code == 200
    assert mine.json()["student_id"] == first["student_id"]

    # A student cannot read another student's assignment: the endpoint is own-only.
    other = my_room(client, second["student"])
    assert other.status_code == 404
    other_attempt = client.get(
        "/api/v1/housing/assignments", headers=second["student"]["headers"]
    )
    assert other_attempt.status_code == 403


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_role_authorization(client, actors, structure):
    ha = structure["ha"]

    for role in [R.student, R.student_affairs, R.system_administrator]:
        user = actors(role)
        response = client.post(
            "/api/v1/housing/floors",
            headers=user["headers"],
            json={"building_name": "ممنوع", "floor_number": "1"},
        )
        assert response.status_code == 403, role
        assert (
            client.get("/api/v1/housing/rooms", headers=user["headers"]).status_code == 403
        )

    # Housing Administration cannot use the student self-service endpoint.
    assert my_room(client, ha).status_code == 403

    blocked = actors(R.housing_administration, must_change=True)
    assert (
        client.get("/api/v1/housing/rooms", headers=blocked["headers"]).status_code == 403
    )

    anonymous = client.post(
        "/api/v1/housing/floors",
        json={"building_name": "بلا جلسة", "floor_number": "1"},
    )
    assert anonymous.status_code == 401


# ---------------------------------------------------------------------------
# Concurrency: capacity conflict under parallel allocation
# ---------------------------------------------------------------------------


def test_concurrent_allocation_to_capacity_one(client, structure, actors):
    ha = structure["ha"]
    room_id = structure["room"]["room_id"]  # capacity 1
    students = [
        accepted_student(client, actors, ha=ha)["student_id"] for _ in range(2)
    ]

    def attempt(student_id):
        return allocate(client, ha, student_id, room_id).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(attempt, students))

    assert results.count(201) == 1, results
    assert all(code in {201, 409, 422} for code in results)

    with SessionLocal.begin() as db:
        active = db.scalar(
            select(func.count(RoomAssignment.assignment_id)).where(
                RoomAssignment.status == A.active,
                RoomAssignment.room_id == room_id,
            )
        )
    assert active == 1


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def test_audit_events_recorded(client, structure, actors):
    ha = structure["ha"]
    state = accepted_student(client, actors, ha=ha)
    room_b = structure["add_room"](
        structure["apartment"]["apartment_id"], "غرفة م " + structure["tag"]
    ).json()
    allocated = allocate(client, ha, state["student_id"], structure["room"]["room_id"]).json()
    transferred = transfer(client, ha, allocated["assignment_id"], room_b["room_id"])
    assert transferred.status_code == 201
    end(client, ha, transferred.json()["assignment_id"]).status_code == 200

    with SessionLocal.begin() as db:
        actions = set(
            db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.actor_id == ha["id"]
                )
            )
        )
    assert {
        "housing.floor_create",
        "housing.apartment_create",
        "housing.room_create",
        "housing.allocate",
        "housing.transfer",
        "housing.end_assignment",
    } <= actions
