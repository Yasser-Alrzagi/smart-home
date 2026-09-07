"""D5 policy: permissions and emergency exits; Student Affairs verifies.

- A student files a permission (dates + reason, pending) or an emergency
  report (reported). Student Affairs reviews both.
- Approving a permission creates a persistent StudentAbsence of type
  "permission" with the same dates and source "permission:<id>".
- Verifying an emergency exit sets exit_verified = True and creates an
  absence of type "emergency" (source "emergency:<id>", start = report date)
  — this is what makes business rule 9.2 auditable: a report does not create
  an absence until the exit is verified. Closing leaves the absence intact.
- Unauthorized absences are not created by this milestone; they are a later
  manual/officer workflow.
"""

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import (
    EmergencyReport,
    PermissionRequest,
    Student,
    StudentAbsence,
)
from app.models.enums import (
    AbsenceType,
    EmergencyReportStatus as E,
    HousingStatus,
    PermissionStatus as P,
    UserRole as R,
)
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.sessions import lock_self

REVIEWER = R.student_affairs

PERMISSION_TRANSITIONS = {
    P.pending: {P.approved, P.rejected, P.cancelled},
    P.approved: set(),
    P.rejected: set(),
    P.cancelled: set(),
}

EMERGENCY_TRANSITIONS = {
    E.reported: {E.under_review},
    E.under_review: {E.verified},
    E.verified: {E.closed},
    E.closed: set(),
}

FORBIDDEN = {HousingStatus.suspended, HousingStatus.terminated}


def reviewer_ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != REVIEWER:
        raise AppError(403, "Student Affairs access required")


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


def _student_name(db, student_id):
    student = db.get(Student, student_id)
    return student.full_name if student else None


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def _permission_dict(db, permission):
    return dict(
        permission_id=permission.permission_id,
        student_id=permission.student_id,
        student_name=_student_name(db, permission.student_id),
        status=permission.status,
        start_date=permission.start_date,
        end_date=permission.end_date,
        reason=permission.reason,
        reviewed_by=permission.reviewed_by,
    )


@account_write
def create_permission(db, ctx, data):
    student_ready(ctx)
    actor = lock_self(db, ctx)
    student_ready(ctx)
    student = _my_student(db, ctx, lock=True)
    if student.housing_status in FORBIDDEN:
        raise AppError(409, "Permission requests are not available in your current status.")
    if data.start_date > data.end_date:
        raise AppError(422, "Leave start must not be after its end.")
    permission = PermissionRequest(
        student_id=student.student_id,
        status=P.pending,
        start_date=data.start_date,
        end_date=data.end_date,
        reason=data.reason,
    )
    db.add(permission)
    db.flush()
    record_event(
        db,
        "permission.create",
        actor=actor,
        target_id=student.user_id,
        details={"permission_id": permission.permission_id},
    )
    return _permission_dict(db, permission)


def my_permissions(db, ctx, offset=0, limit=20):
    student_ready(ctx)
    student = _my_student(db, ctx)
    query = select(PermissionRequest).where(
        PermissionRequest.student_id == student.student_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(PermissionRequest.start_date.desc()).offset(offset).limit(limit))
    return dict(
        items=[_permission_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_permissions(db, ctx, status=None, offset=0, limit=20):
    reviewer_ready(ctx)
    query = select(PermissionRequest)
    if status is not None:
        query = query.where(PermissionRequest.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(PermissionRequest.start_date.desc()).offset(offset).limit(limit)
    )
    return dict(
        items=[_permission_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@account_write
def review_permission(db, ctx, permission_id, action):
    reviewer_ready(ctx)
    actor = lock_self(db, ctx)
    reviewer_ready(ctx)
    permission = db.scalar(
        select(PermissionRequest)
        .where(PermissionRequest.permission_id == permission_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if permission is None:
        raise AppError(404, "Permission request not found")
    previous = permission.status
    if action not in {"approve", "reject", "cancel"}:
        raise AppError(422, "Unsupported action")
    target = {"approve": P.approved, "reject": P.rejected, "cancel": P.cancelled}[action]
    if target not in PERMISSION_TRANSITIONS[previous]:
        raise AppError(409, "Invalid permission transition")
    if action == "cancel" and previous != P.pending:
        raise AppError(409, "Only pending requests can be cancelled")
    permission.status = target
    if target != P.pending:
        permission.reviewed_by = actor.user_id
    if action == "approve":
        db.add(
            StudentAbsence(
                student_id=permission.student_id,
                absence_type=AbsenceType.permission,
                start_date=permission.start_date,
                end_date=permission.end_date,
                source=f"permission:{permission.permission_id}",
                notes="غياب مأذون صادر عن طلب إذن معتمد.",
            )
        )
    db.flush()
    record_event(
        db,
        "permission.update",
        actor=actor,
        details={
            "permission_id": permission.permission_id,
            "from_status": previous.value,
            "to_status": target.value,
        },
    )
    return _permission_dict(db, permission)


@account_write
def cancel_permission(db, ctx, permission_id):
    student_ready(ctx)
    actor = lock_self(db, ctx)
    student_ready(ctx)
    permission = db.scalar(
        select(PermissionRequest)
        .where(PermissionRequest.permission_id == permission_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if permission is None:
        raise AppError(404, "Permission request not found")
    student = _my_student(db, ctx)
    if permission.student_id != student.student_id:
        raise AppError(404, "Permission request not found")
    if permission.status != P.pending:
        raise AppError(409, "Only pending requests can be cancelled by the student.")
    permission.status = P.cancelled
    db.flush()
    record_event(
        db,
        "permission.cancel",
        actor=actor,
        target_id=student.user_id,
        details={"permission_id": permission.permission_id},
    )
    return _permission_dict(db, permission)


# ---------------------------------------------------------------------------
# Emergency reports
# ---------------------------------------------------------------------------


def _report_dict(db, report):
    return dict(
        report_id=report.report_id,
        student_id=report.student_id,
        student_name=_student_name(db, report.student_id),
        reported_at=report.reported_at,
        description=report.description,
        status=report.status,
        exit_verified=report.exit_verified,
        absence_id=report.absence_id,
    )


@account_write
def create_report(db, ctx, data):
    student_ready(ctx)
    actor = lock_self(db, ctx)
    student_ready(ctx)
    student = _my_student(db, ctx, lock=True)
    report = EmergencyReport(
        student_id=student.student_id,
        description=data.description,
        status=E.reported,
    )
    db.add(report)
    db.flush()
    record_event(
        db,
        "emergency.create",
        actor=actor,
        target_id=student.user_id,
        details={"emergency_report_id": report.report_id},
    )
    return _report_dict(db, report)


def my_reports(db, ctx, offset=0, limit=20):
    student_ready(ctx)
    student = _my_student(db, ctx)
    query = select(EmergencyReport).where(
        EmergencyReport.student_id == student.student_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(EmergencyReport.reported_at.desc()).offset(offset).limit(limit))
    return dict(
        items=[_report_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_reports(db, ctx, status=None, offset=0, limit=20):
    reviewer_ready(ctx)
    query = select(EmergencyReport)
    if status is not None:
        query = query.where(EmergencyReport.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(EmergencyReport.reported_at.desc()).offset(offset).limit(limit))
    return dict(
        items=[_report_dict(db, row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@account_write
def review_report(db, ctx, report_id, action):
    reviewer_ready(ctx)
    actor = lock_self(db, ctx)
    reviewer_ready(ctx)
    report = db.scalar(
        select(EmergencyReport)
        .where(EmergencyReport.report_id == report_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if report is None:
        raise AppError(404, "Emergency report not found")
    previous = report.status
    target = {"start": E.under_review, "verify": E.verified, "close": E.closed}.get(action)
    if target is None:
        raise AppError(422, "Unsupported action")
    if target not in EMERGENCY_TRANSITIONS[previous]:
        raise AppError(409, "Invalid emergency report transition")
    report.status = target
    report.handled_by = actor.user_id
    if action == "verify":
        report.exit_verified = True
        absence = StudentAbsence(
            student_id=report.student_id,
            absence_type=AbsenceType.emergency,
            start_date=report.reported_at.date(),
            end_date=None,
            source=f"emergency:{report.report_id}",
            notes="غياب طارئ صادر عن بلاغ تم التحقق من خروجه.",
        )
        db.add(absence)
        db.flush()
        report.absence_id = absence.absence_id
    db.flush()
    record_event(
        db,
        "emergency.update",
        actor=actor,
        details={
            "emergency_report_id": report.report_id,
            "from_status": previous.value,
            "to_status": target.value,
        },
    )
    return _report_dict(db, report)


# ---------------------------------------------------------------------------
# Absences (read-only in D5)
# ---------------------------------------------------------------------------


def _absence_dict(absence):
    return dict(
        absence_id=absence.absence_id,
        absence_type=absence.absence_type,
        start_date=absence.start_date,
        end_date=absence.end_date,
        source=absence.source,
        notes=absence.notes,
    )


def my_absences(db, ctx, offset=0, limit=20):
    student_ready(ctx)
    student = _my_student(db, ctx)
    query = select(StudentAbsence).where(StudentAbsence.student_id == student.student_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(StudentAbsence.start_date.desc()).offset(offset).limit(limit))
    return dict(
        items=[_absence_dict(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


def list_absences(db, ctx, absence_type=None, offset=0, limit=20):
    reviewer_ready(ctx)
    query = (
        select(StudentAbsence, Student)
        .join(Student, Student.student_id == StudentAbsence.student_id)
    )
    if absence_type is not None:
        query = query.where(StudentAbsence.absence_type == absence_type)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(StudentAbsence.start_date.desc()).offset(offset).limit(limit)
    ).all()
    return dict(
        items=[
            {
                **_absence_dict(absence),
                "student_id": student.student_id,
                "student_name": student.full_name,
            }
            for absence, student in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
