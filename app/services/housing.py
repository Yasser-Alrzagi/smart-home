"""D4 policy: Housing Administration allocates rooms, runs transfers and ends.

Rules approved with the housing milestone:

- Only students with an ACCEPTED application may be allocated a room. Approval
  is not allocation and allocation is never automatic.
- One active assignment per student; full history (ended/transferred) is kept.
- Capacity is enforced at the business layer under room row locks: active
  assignments never exceed rooms.capacity, and two allocations to the same
  room cannot both succeed.
- rooms.status is derived from occupancy while it is an occupancy state
  (available/partially_occupied/fully_occupied). maintenance/closed are
  officer-declared and refuse new allocations until reset.
- First allocation moves housing_status applicant -> active and records a
  student_status_history entry. Ending an assignment never silently changes
  the housing status (that lifecycle is a separate, later workflow).
- Lock order: users (actor) -> students -> rooms (sorted room_id) ->
  assignments. The account_write guard converts deadlock/conflict codes to 409.

Occupancy is computed arithmetically (before/after the change) because the
unit of work runs with autoflush=False: a counted query would not see pending
assignment rows.

No new tables are required: floors/apartments/rooms/room_assignments exist
since D1. D4 is business logic, API, UI and tests only.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.models import (
    Apartment,
    Application,
    Floor,
    Room,
    RoomAssignment,
    Student,
    StudentStatusHistory,
    utcnow,
)
from app.models.enums import (
    ApplicationStatus as S,
    HousingStatus,
    RoomAssignmentStatus,
    RoomStatus,
    StatusType,
    UserRole as R,
)
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.sessions import lock_self

# Role that operates the housing product. System Administrator, Student Affairs
# and officers cannot allocate rooms; admin manages accounts only.
OFFICER = R.housing_administration

# The officer may declare these manually; occupancy states are derived.
MANUAL_STATES = {RoomStatus.available, RoomStatus.maintenance, RoomStatus.closed}
OCCUPANCY_STATES = {
    RoomStatus.available,
    RoomStatus.partially_occupied,
    RoomStatus.fully_occupied,
}


def ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != OFFICER:
        raise AppError(403, "Housing Administration access required")


def student_ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != R.student:
        raise AppError(403, "Student access required")


def status_for(occupancy, capacity):
    """Pure occupancy-state derivation; used by the service and unit tests."""
    if occupancy <= 0:
        return RoomStatus.available
    if occupancy < capacity:
        return RoomStatus.partially_occupied
    return RoomStatus.fully_occupied


def _derive(room, occupancy):
    """Re-derive the room status after an occupancy change, unless declared."""
    if room.status in OCCUPANCY_STATES:
        room.status = status_for(occupancy, room.capacity)


def _lock_actor(db, ctx):
    actor = lock_self(db, ctx)
    ready(ctx)
    return actor


def _flush(db):
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "args", (None,))[0] == 1062:
            raise AppError(409, "A record with the same identifiers already exists.") from None
        raise


def _student_locked(db, student_id):
    student = db.scalar(
        select(Student)
        .where(Student.student_id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if student is None:
        raise AppError(404, "Student not found")
    return student


def _room_locked(db, room_id):
    room = db.scalar(
        select(Room)
        .where(Room.room_id == room_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if room is None:
        raise AppError(404, "Room not found")
    return room


def _assignment_locked(db, assignment_id):
    assignment = db.scalar(
        select(RoomAssignment)
        .where(RoomAssignment.assignment_id == assignment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if assignment is None:
        raise AppError(404, "Assignment not found")
    return assignment


def _occupancy(db, room_id):
    """Active assignments for a room (caller owns the room row lock)."""
    return db.scalar(
        select(func.count(RoomAssignment.assignment_id)).where(
            RoomAssignment.room_id == room_id,
            RoomAssignment.status == RoomAssignmentStatus.active,
        )
    )


def _accepted_application(db, student):
    application = db.scalar(
        select(Application)
        .where(
            Application.student_id == student.student_id,
            Application.status == S.accepted,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if application is None:
        raise AppError(
            409, "Only students with an accepted application can be allocated a room."
        )
    return application


def _room_dict(db, room, apartment=None, floor=None):
    if apartment is None:
        apartment = db.get(Apartment, room.apartment_id)
    if floor is None and apartment is not None:
        floor = db.get(Floor, apartment.floor_id)
    return dict(
        room_id=room.room_id,
        apartment_id=room.apartment_id,
        building_name=floor.building_name if floor else None,
        floor_number=floor.floor_number if floor else None,
        apartment_number=apartment.apartment_number if apartment else None,
        room_number=room.room_number,
        capacity=room.capacity,
        status=room.status,
        occupancy=_occupancy(db, room.room_id),
    )


def _assignment_dict(
    db, assignment, student, room, apartment, floor, occupancy=None
):
    return dict(
        assignment_id=assignment.assignment_id,
        student_id=student.student_id,
        student_name=student.full_name,
        university=student.university,
        room_id=room.room_id,
        building_name=floor.building_name,
        floor_number=floor.floor_number,
        apartment_number=apartment.apartment_number,
        room_number=room.room_number,
        capacity=room.capacity,
        status=assignment.status,
        assignment_date=assignment.assignment_date,
        end_date=assignment.end_date,
        room_status=room.status,
        occupancy=occupancy if occupancy is not None else _occupancy(
            db, room.room_id
        ),
    )


def _assignment_summary(db, assignment):
    row = db.execute(
        select(RoomAssignment, Student, Room, Apartment, Floor)
        .join(Student, Student.student_id == RoomAssignment.student_id)
        .join(Room, Room.room_id == RoomAssignment.room_id)
        .join(Apartment, Apartment.apartment_id == Room.apartment_id)
        .join(Floor, Floor.floor_id == Apartment.floor_id)
        .where(RoomAssignment.assignment_id == assignment.assignment_id)
    ).first()
    if row is None:
        raise AppError(404, "Assignment not found")
    record, student, room, apartment, floor = row
    return _assignment_dict(db, record, student, room, apartment, floor)


# ---------------------------------------------------------------------------
# Housing structure: floors -> apartments -> rooms (officer managed)
# ---------------------------------------------------------------------------


def list_floors(db, ctx):
    ready(ctx)
    rows = db.execute(
        select(Floor).order_by(Floor.building_name, Floor.floor_number)
    ).scalars()
    return [
        dict(
            floor_id=floor.floor_id,
            building_name=floor.building_name,
            floor_number=floor.floor_number,
        )
        for floor in rows
    ]


@account_write
def create_floor(db, ctx, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    if db.scalar(
        select(Floor.floor_id)
        .where(
            Floor.building_name == data.building_name,
            Floor.floor_number == data.floor_number,
        )
        .with_for_update()
    ):
        raise AppError(409, "This building/floor already exists.")
    floor = Floor(building_name=data.building_name, floor_number=data.floor_number)
    db.add(floor)
    _flush(db)
    record_event(
        db,
        "housing.floor_create",
        actor=actor,
        details={"floor_id": floor.floor_id},
    )
    return dict(
        floor_id=floor.floor_id,
        building_name=floor.building_name,
        floor_number=floor.floor_number,
    )


def list_apartments(db, ctx, floor_id=None):
    ready(ctx)
    query = select(Apartment, Floor).join(
        Floor, Apartment.floor_id == Floor.floor_id
    )
    if floor_id is not None:
        query = query.where(Apartment.floor_id == floor_id)
    rows = db.execute(
        query.order_by(
            Floor.building_name, Floor.floor_number, Apartment.apartment_number
        )
    ).all()
    return [
        dict(
            apartment_id=apartment.apartment_id,
            floor_id=apartment.floor_id,
            building_name=floor.building_name,
            floor_number=floor.floor_number,
            apartment_number=apartment.apartment_number,
        )
        for apartment, floor in rows
    ]


@account_write
def create_apartment(db, ctx, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    floor = db.scalar(
        select(Floor)
        .where(Floor.floor_id == data.floor_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if floor is None:
        raise AppError(404, "Floor not found")
    if db.scalar(
        select(Apartment.apartment_id)
        .where(
            Apartment.floor_id == data.floor_id,
            Apartment.apartment_number == data.apartment_number,
        )
        .with_for_update()
    ):
        raise AppError(409, "This apartment already exists on the floor.")
    apartment = Apartment(
        floor_id=data.floor_id, apartment_number=data.apartment_number
    )
    db.add(apartment)
    _flush(db)
    record_event(
        db,
        "housing.apartment_create",
        actor=actor,
        details={"floor_id": floor.floor_id, "apartment_id": apartment.apartment_id},
    )
    return dict(
        apartment_id=apartment.apartment_id,
        floor_id=apartment.floor_id,
        building_name=floor.building_name,
        floor_number=floor.floor_number,
        apartment_number=apartment.apartment_number,
    )


def list_rooms(db, ctx, status=None, building=None, offset=0, limit=20):
    ready(ctx)
    query = (
        select(Room, Apartment, Floor)
        .join(Apartment, Room.apartment_id == Apartment.apartment_id)
        .join(Floor, Apartment.floor_id == Floor.floor_id)
    )
    if status is not None:
        query = query.where(Room.status == status)
    if building is not None:
        query = query.where(Floor.building_name == building)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(
            Floor.building_name,
            Floor.floor_number,
            Apartment.apartment_number,
            Room.room_number,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return dict(
        items=[
            _room_dict(db, room, apartment, floor)
            for room, apartment, floor in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@account_write
def create_room(db, ctx, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    apartment = db.scalar(
        select(Apartment)
        .where(Apartment.apartment_id == data.apartment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if apartment is None:
        raise AppError(404, "Apartment not found")
    if db.scalar(
        select(Room.room_id)
        .where(
            Room.apartment_id == data.apartment_id,
            Room.room_number == data.room_number,
        )
        .with_for_update()
    ):
        raise AppError(409, "This room number already exists in the apartment.")
    room = Room(
        apartment_id=data.apartment_id,
        room_number=data.room_number,
        capacity=data.capacity,
        status=RoomStatus.available,
    )
    db.add(room)
    _flush(db)
    record_event(
        db,
        "housing.room_create",
        actor=actor,
        details={"apartment_id": apartment.apartment_id, "room_id": room.room_id},
    )
    return _room_dict(db, room=room)


@account_write
def update_room(db, ctx, room_id, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    room = _room_locked(db, room_id)
    occupancy = _occupancy(db, room.room_id)
    if data.room_number is not None:
        if data.room_number != room.room_number and db.scalar(
            select(Room.room_id)
            .where(
                Room.apartment_id == room.apartment_id,
                Room.room_number == data.room_number,
                Room.room_id != room_id,
            )
            .with_for_update()
        ):
            raise AppError(409, "This room number already exists in the apartment.")
        room.room_number = data.room_number
    if data.capacity is not None:
        if data.capacity < occupancy:
            raise AppError(
                409, "Capacity cannot be below the current number of occupants."
            )
        room.capacity = data.capacity
    if data.status is not None:
        if data.status not in MANUAL_STATES:
            raise AppError(
                422,
                "Occupancy states are derived automatically; set available, maintenance or closed.",
            )
        room.status = data.status
    _derive(room, occupancy)
    _flush(db)
    record_event(
        db,
        "housing.room_update",
        actor=actor,
        details={"room_id": room.room_id},
    )
    return _room_dict(db, room=room)


# ---------------------------------------------------------------------------
# Assignments: allocate, transfer, end
# ---------------------------------------------------------------------------


def eligible_students(db, ctx, offset=0, limit=20):
    """Accepted students without an active assignment, oldest application first."""
    ready(ctx)
    active_exists = (
        select(RoomAssignment.assignment_id)
        .where(
            RoomAssignment.student_id == Student.student_id,
            RoomAssignment.status == RoomAssignmentStatus.active,
        )
        .exists()
    )
    base = (
        select(Student, Application)
        .join(Application, Application.student_id == Student.student_id)
        .where(Application.status == S.accepted, ~active_exists)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.order_by(Application.application_date, Application.application_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return dict(
        items=[
            dict(
                student_id=student.student_id,
                full_name=student.full_name,
                university=student.university,
                major=student.major,
                application_id=application.application_id,
                application_date=application.application_date,
            )
            for student, application in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_assignments(db, ctx, status=None, offset=0, limit=20):
    ready(ctx)
    query = (
        select(RoomAssignment, Student, Room, Apartment, Floor)
        .join(Student, RoomAssignment.student_id == Student.student_id)
        .join(Room, RoomAssignment.room_id == Room.room_id)
        .join(Apartment, Room.apartment_id == Apartment.apartment_id)
        .join(Floor, Apartment.floor_id == Floor.floor_id)
    )
    if status is not None:
        query = query.where(RoomAssignment.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(
            RoomAssignment.assignment_date.desc(), RoomAssignment.assignment_id
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return dict(
        items=[
            _assignment_dict(db, assignment, student, room, apartment, floor)
            for assignment, student, room, apartment, floor in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@account_write
def allocate(db, ctx, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    student = _student_locked(db, data.student_id)
    if student.housing_status in {
        HousingStatus.suspended,
        HousingStatus.terminated,
    }:
        raise AppError(
            409, "Student is not eligible for allocation in their current status."
        )
    _accepted_application(db, student)
    if db.scalar(
        select(RoomAssignment.assignment_id)
        .where(
            RoomAssignment.student_id == student.student_id,
            RoomAssignment.status == RoomAssignmentStatus.active,
        )
        .with_for_update()
    ):
        raise AppError(409, "The student already has an active assignment.")
    room = _room_locked(db, data.room_id)
    if room.status in {RoomStatus.maintenance, RoomStatus.closed}:
        raise AppError(409, "The room is not available for allocation.")
    occupancy = _occupancy(db, room.room_id)
    if occupancy >= room.capacity:
        raise AppError(422, "Room capacity would be exceeded; the room is full.")
    assignment = RoomAssignment(
        student_id=student.student_id,
        room_id=room.room_id,
        assigned_by=actor.user_id,
        assignment_date=utcnow(),
        status=RoomAssignmentStatus.active,
    )
    db.add(assignment)
    if student.housing_status == HousingStatus.applicant:
        student.housing_status = HousingStatus.active
        db.add(
            StudentStatusHistory(
                student_id=student.student_id,
                status_type=StatusType.housing,
                old_status=HousingStatus.applicant.value,
                new_status=HousingStatus.active.value,
                changed_by=actor.user_id,
                notes="تخصيص غرفة؛ نقلت الحالة من متقدم إلى مقيم.",
            )
        )
    _derive(room, occupancy + 1)
    _flush(db)
    record_event(
        db,
        "housing.allocate",
        actor=actor,
        target_id=student.user_id,
        details={
            "assignment_id": assignment.assignment_id,
            "student_id": student.student_id,
            "room_id": room.room_id,
            "occupancy": occupancy + 1,
            "capacity": room.capacity,
            "room_status": room.status.value,
        },
    )
    return _assignment_summary(db, assignment)


@account_write
def transfer(db, ctx, assignment_id, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    assignment = _assignment_locked(db, assignment_id)
    if assignment.status != RoomAssignmentStatus.active:
        raise AppError(409, "Only active assignments can be transferred.")
    student = _student_locked(db, assignment.student_id)
    if student.housing_status in {
        HousingStatus.suspended,
        HousingStatus.terminated,
    }:
        raise AppError(409, "Student is not eligible in their current status.")
    if data.to_room_id == assignment.room_id:
        raise AppError(409, "The student is already assigned to that room.")
    rooms = {
        room.room_id: room
        for room in db.scalars(
            select(Room)
            .where(Room.room_id.in_({assignment.room_id, data.to_room_id}))
            .order_by(Room.room_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    old_room = rooms.get(assignment.room_id)
    new_room = rooms.get(data.to_room_id)
    if old_room is None or new_room is None:
        raise AppError(404, "Room not found")
    if new_room.status in {RoomStatus.maintenance, RoomStatus.closed}:
        raise AppError(409, "The target room is not available for allocation.")
    old_occupancy = _occupancy(db, old_room.room_id)
    new_occupancy = _occupancy(db, new_room.room_id)
    if new_occupancy >= new_room.capacity:
        raise AppError(422, "Target room capacity would be exceeded; it is full.")
    assignment.status = RoomAssignmentStatus.transferred
    assignment.end_date = utcnow()
    new_assignment = RoomAssignment(
        student_id=student.student_id,
        room_id=new_room.room_id,
        assigned_by=actor.user_id,
        assignment_date=utcnow(),
        status=RoomAssignmentStatus.active,
    )
    db.add(new_assignment)
    _derive(old_room, old_occupancy - 1)
    _derive(new_room, new_occupancy + 1)
    _flush(db)
    record_event(
        db,
        "housing.transfer",
        actor=actor,
        target_id=student.user_id,
        details={
            "assignment_id": assignment.assignment_id,
            "student_id": student.student_id,
            "from_room_id": old_room.room_id,
            "to_room_id": new_room.room_id,
        },
    )
    return _assignment_summary(db, new_assignment)


@account_write
def end_assignment(db, ctx, assignment_id):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    assignment = _assignment_locked(db, assignment_id)
    if assignment.status != RoomAssignmentStatus.active:
        raise AppError(409, "Only active assignments can be ended.")
    student = _student_locked(db, assignment.student_id)
    room = _room_locked(db, assignment.room_id)
    occupancy = _occupancy(db, room.room_id)
    assignment.status = RoomAssignmentStatus.ended
    assignment.end_date = utcnow()
    _derive(room, occupancy - 1)
    _flush(db)
    record_event(
        db,
        "housing.end_assignment",
        actor=actor,
        target_id=student.user_id,
        details={
            "assignment_id": assignment.assignment_id,
            "student_id": student.student_id,
            "room_id": room.room_id,
            "occupancy": occupancy - 1,
            "room_status": room.status.value,
        },
    )
    return _assignment_summary(db, assignment)


# ---------------------------------------------------------------------------
# Student self-service: my room
# ---------------------------------------------------------------------------


def my_assignment(db, ctx):
    student_ready(ctx)
    student = db.scalar(
        select(Student).where(Student.user_id == ctx.user.user_id)
    )
    if student is None:
        raise AppError(404, "Student profile not found")
    current = db.execute(
        select(RoomAssignment, Room, Apartment, Floor)
        .join(Room, RoomAssignment.room_id == Room.room_id)
        .join(Apartment, Room.apartment_id == Apartment.apartment_id)
        .join(Floor, Apartment.floor_id == Floor.floor_id)
        .where(
            RoomAssignment.student_id == student.student_id,
            RoomAssignment.status == RoomAssignmentStatus.active,
        )
    ).first()
    if current is None:
        raise AppError(
            404, "No room is currently assigned to you; approval is not allocation."
        )
    assignment, room, apartment, floor = current
    history_rows = db.execute(
        select(RoomAssignment, Room, Apartment, Floor)
        .join(Room, RoomAssignment.room_id == Room.room_id)
        .join(Apartment, Room.apartment_id == Apartment.apartment_id)
        .join(Floor, Apartment.floor_id == Floor.floor_id)
        .where(
            RoomAssignment.student_id == student.student_id,
            RoomAssignment.status != RoomAssignmentStatus.active,
        )
        .order_by(RoomAssignment.end_date.desc(), RoomAssignment.assignment_id)
    ).all()
    return {
        **_assignment_dict(db, assignment, student, room, apartment, floor),
        "history": [
            dict(
                assignment_id=item.assignment_id,
                room_number=item_room.room_number,
                building_name=item_floor.building_name,
                floor_number=item_floor.floor_number,
                apartment_number=item_apartment.apartment_number,
                status=item.status,
                assignment_date=item.assignment_date,
                end_date=item.end_date,
            )
            for item, item_room, item_apartment, item_floor in history_rows
        ],
    }
