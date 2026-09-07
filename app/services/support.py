"""D5 policy: students file complaints and maintenance requests; officers act.

- Complaints are handled by Housing Administration (the housing owner role);
  a complaint tracks open -> under_review -> resolved -> closed with the
  resolution text stored on the record. No deletion.
- Maintenance requests are handled by the Maintenance Officer with statuses
  pending -> assigned -> in_progress -> resolved -> closed. The room, when
  provided, must be the student's currently active room; a student without an
  active assignment cannot attach a room.
- Students see only their own records; officers see all records for their
  remit. Both lists are paginated and status-filterable.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.models import (
    Complaint,
    MaintenanceRequest,
    RoomAssignment,
    Student,
    utcnow,
)
from app.models.enums import (
    ComplaintStatus as C,
    HousingStatus,
    MaintenanceStatus as M,
    RoomAssignmentStatus as A,
    UserRole as R,
)
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.notifications import notify_role, notify_user
from app.services.sessions import lock_self

COMPLAINT_HANDLER = R.housing_administration
MAINTENANCE_HANDLER = R.maintenance_officer

COMPLAINT_TRANSITIONS = {
    C.open: {C.under_review},
    C.under_review: {C.resolved},
    C.resolved: {C.closed},
    C.closed: set(),
}

MAINTENANCE_TRANSITIONS = {
    M.pending: {M.assigned},
    M.assigned: {M.in_progress, M.resolved},
    M.in_progress: {M.resolved},
    M.resolved: {M.closed},
    M.closed: set(),
}

FORBIDDEN = {HousingStatus.suspended, HousingStatus.terminated}


def _handler_ready(ctx, role):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != role:
        raise AppError(403, "Operation not permitted")


def student_ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != R.student:
        raise AppError(403, "Student access required")


def _my_student(db, ctx, *, lock=False):
    student_ready(ctx)
    query = select(Student).where(Student.user_id == ctx.user.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    student = db.scalar(query)
    if student is None:
        raise AppError(404, "Student profile not found")
    return student


def _row(db, model, pk, pk_name, lock=False):
    query = select(model).where(getattr(model, pk_name) == pk)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        raise AppError(404, "Record not found")
    return row


def _flush(db):
    try:
        db.flush()
    except IntegrityError:
        raise


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------


def _complaint_dict(db, complaint):
    student = db.get(Student, complaint.student_id)
    return dict(
        complaint_id=complaint.complaint_id,
        student_id=complaint.student_id,
        student_name=student.full_name if student else None,
        university=student.university if student else None,
        category=complaint.category,
        description=complaint.description,
        status=complaint.status,
        resolution=complaint.resolution,
        created_at=complaint.created_at,
        updated_at=complaint.updated_at,
    )


@account_write
def create_complaint(db, ctx, data):
    student_ready(ctx)
    actor = lock_self(db, ctx)
    student_ready(ctx)
    student = _my_student(db, ctx, lock=True)
    if student.housing_status in FORBIDDEN:
        raise AppError(409, "Complaints are not available in your current status.")
    complaint = Complaint(
        student_id=student.student_id,
        category=data.category,
        description=data.description,
        status=C.open,
    )
    db.add(complaint)
    _flush(db)
    record_event(
        db,
        "complaint.create",
        actor=actor,
        target_id=student.user_id,
        details={"complaint_id": complaint.complaint_id},
    )
    notify_role(
        db,
        R.housing_administration,
        "شكوى جديدة",
        f"وصلت شكوى من «{student.full_name}» ({complaint.category}).",
        exclude_user_id=actor.user_id,
    )
    return _complaint_dict(db, complaint)


def my_complaints(db, ctx, offset=0, limit=20):
    student_ready(ctx)
    student = _my_student(db, ctx)
    query = select(Complaint).where(Complaint.student_id == student.student_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Complaint.created_at.desc()).offset(offset).limit(limit)
    )
    return dict(
        items=[_complaint_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_complaints(db, ctx, status=None, offset=0, limit=20):
    _handler_ready(ctx, COMPLAINT_HANDLER)
    query = select(Complaint)
    if status is not None:
        query = query.where(Complaint.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Complaint.created_at.desc()).offset(offset).limit(limit)
    )
    return dict(
        items=[_complaint_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@account_write
def update_complaint(db, ctx, complaint_id, action, resolution=None):
    _handler_ready(ctx, COMPLAINT_HANDLER)
    actor = lock_self(db, ctx)
    _handler_ready(ctx, COMPLAINT_HANDLER)
    complaint = _row(db, Complaint, complaint_id, "complaint_id", lock=True)
    previous = complaint.status
    if action == "start":
        target, need_resolution = C.under_review, False
    elif action == "resolve":
        target, need_resolution = C.resolved, True
    elif action == "close":
        target, need_resolution = C.closed, True
    else:
        raise AppError(422, "Unsupported action")
    if target not in COMPLAINT_TRANSITIONS[previous]:
        raise AppError(409, "Invalid complaint transition")
    if need_resolution and not (resolution or "").strip():
        raise AppError(422, "A clear resolution is required.")
    complaint.status = target
    if resolution is not None:
        complaint.resolution = resolution.strip() or complaint.resolution
    complaint.handled_by = actor.user_id
    complaint.updated_at = utcnow()
    _flush(db)
    record_event(
        db,
        "complaint.update",
        actor=actor,
        details={
            "complaint_id": complaint.complaint_id,
            "from_status": previous.value,
            "to_status": target.value,
        },
    )
    student = db.get(Student, complaint.student_id)
    if student is not None:
        notify_user(
            db,
            user_id=student.user_id,
            title="تحديث شكواك",
            message=f"شكواك ({complaint.category}) أصبحت {target.value}.",
        )
    return _complaint_dict(db, complaint)


# ---------------------------------------------------------------------------
# Maintenance requests
# ---------------------------------------------------------------------------


def _maintenance_dict(db, request):
    student = db.get(Student, request.student_id)
    from app.models import Room

    room = db.get(Room, request.room_id) if request.room_id else None
    return dict(
        request_id=request.request_id,
        student_id=request.student_id,
        student_name=student.full_name if student else None,
        university=student.university if student else None,
        room_id=request.room_id,
        building_name=room.apartment.floor.building_name if room else None,
        floor_number=room.apartment.floor.floor_number if room else None,
        apartment_number=room.apartment.apartment_number if room else None,
        room_number=room.room_number if room else None,
        problem_type=request.problem_type,
        description=request.description,
        status=request.status,
        resolution=request.resolution,
        created_at=request.created_at,
        updated_at=request.updated_at,
    )


@account_write
def create_maintenance(db, ctx, data):
    student_ready(ctx)
    actor = lock_self(db, ctx)
    student_ready(ctx)
    student = _my_student(db, ctx, lock=True)
    if student.housing_status in FORBIDDEN:
        raise AppError(409, "Maintenance requests are not available in your current status.")
    if data.room_id is not None:
        active = db.scalar(
            select(RoomAssignment.room_id)
            .where(
                RoomAssignment.student_id == student.student_id,
                RoomAssignment.status == A.active,
                RoomAssignment.room_id == data.room_id,
            )
            .with_for_update()
        )
        if active is None:
            raise AppError(422, "The room is not your currently assigned room.")
    request = MaintenanceRequest(
        student_id=student.student_id,
        room_id=data.room_id,
        problem_type=data.problem_type,
        description=data.description,
        status=M.pending,
    )
    db.add(request)
    _flush(db)
    record_event(
        db,
        "maintenance.create",
        actor=actor,
        target_id=student.user_id,
        details={"maintenance_request_id": request.request_id},
    )
    notify_role(
        db,
        R.maintenance_officer,
        "طلب صيانة جديد",
        f"وصل طلب صيانة من «{student.full_name}» ({data.problem_type}).",
        exclude_user_id=actor.user_id,
    )
    return _maintenance_dict(db, request)


def my_maintenance(db, ctx, offset=0, limit=20):
    student_ready(ctx)
    student = _my_student(db, ctx)
    query = select(MaintenanceRequest).where(
        MaintenanceRequest.student_id == student.student_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(MaintenanceRequest.created_at.desc()).offset(offset).limit(limit)
    )
    return dict(
        items=[_maintenance_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_maintenance(db, ctx, status=None, offset=0, limit=20):
    _handler_ready(ctx, MAINTENANCE_HANDLER)
    query = select(MaintenanceRequest)
    if status is not None:
        query = query.where(MaintenanceRequest.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(MaintenanceRequest.created_at.desc()).offset(offset).limit(limit)
    )
    return dict(
        items=[_maintenance_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@account_write
def update_maintenance(db, ctx, request_id, action, resolution=None):
    _handler_ready(ctx, MAINTENANCE_HANDLER)
    actor = lock_self(db, ctx)
    _handler_ready(ctx, MAINTENANCE_HANDLER)
    request = _row(db, MaintenanceRequest, request_id, "request_id", lock=True)
    previous = request.status
    action_map = {
        "assign": M.assigned,
        "progress": M.in_progress,
        "resolve": M.resolved,
        "close": M.closed,
    }
    if action not in action_map:
        raise AppError(422, "Unsupported action")
    target = action_map[action]
    if target not in MAINTENANCE_TRANSITIONS[previous]:
        raise AppError(409, "Invalid maintenance transition")
    if target in {M.resolved, M.closed} and not (resolution or "").strip():
        raise AppError(422, "A clear resolution is required.")
    request.status = target
    if resolution is not None:
        request.resolution = resolution.strip() or request.resolution
    request.handled_by = actor.user_id
    request.updated_at = utcnow()
    _flush(db)
    record_event(
        db,
        "maintenance.update",
        actor=actor,
        details={
            "maintenance_request_id": request.request_id,
            "from_status": previous.value,
            "to_status": target.value,
        },
    )
    student = db.get(Student, request.student_id)
    if student is not None:
        notify_user(
            db,
            user_id=student.user_id,
            title="تحديث طلب الصيانة",
            message=f"طلب الصيانة ({request.problem_type}) أصبح {target.value}.",
        )
    return _maintenance_dict(db, request)
