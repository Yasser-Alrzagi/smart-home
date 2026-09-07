"""D7 policy: daily attendance records and the documented unauthorized absence.

- Housing Administration records daily attendance per student per date
  (Present/Late/Absent/Excused), one row per student per date (upsert).
- Marking a day ``Absent`` produces a persistent ``Unauthorized``
  StudentAbsence (source ``attendance:<record_id>``) once per record, unless
  an approved permission or verified emergency already covers that date —
  and never inside the reporter window that already generated one.
- Documented absences are never deleted: correcting the day's status later
  does not erase the historical absence record.
- Students read their own ledger; Housing Administration reads/writes all.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import (
    AttendanceRecord,
    EmergencyReport,
    PermissionRequest,
    Student,
    StudentAbsence,
    utcnow,
)
from app.models.enums import (
    AbsenceType,
    AttendanceStatus,
    PermissionStatus,
    UserRole as R,
)
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.sessions import lock_self

RECORDER = R.housing_administration


def _recorder_ready(ctx):
    if ctx.user.role != RECORDER:
        raise AppError(403, "Housing Administration access required")


def _student_name(db, student_id):
    return db.get(Student, student_id).full_name if db.get(Student, student_id) else None


def _covers(db, student_id, day):
    """An approved permission or verified emergency that covers the day."""
    perm = db.scalar(
        select(PermissionRequest.permission_id).where(
            PermissionRequest.student_id == student_id,
            PermissionRequest.status == PermissionStatus.approved,
            PermissionRequest.start_date <= day,
            PermissionRequest.end_date >= day,
        )
    )
    if perm:
        return True
    day_start = datetime.combine(day, time.min)
    day_end = day_start + timedelta(days=1)
    rep = db.scalar(
        select(EmergencyReport.report_id).where(
            EmergencyReport.student_id == student_id,
            EmergencyReport.exit_verified.is_(True),
            EmergencyReport.reported_at >= day_start,
            EmergencyReport.reported_at < day_end,
        )
    )
    return bool(rep)


@account_write
def record_daily(db, ctx, data):
    _recorder_ready(ctx)
    actor = lock_self(db, ctx)
    _recorder_ready(ctx)
    day = data.record_date
    items = []
    for entry in data.records:
        student = db.get(Student, entry.student_id)
        if student is None:
            raise AppError(422, f"Unknown student: {entry.student_id}")
        row = db.scalar(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.student_id == student.student_id,
                AttendanceRecord.record_date == day,
            )
            .with_for_update()
        )
        if row is None:
            row = AttendanceRecord(
                student_id=student.student_id,
                record_date=day,
                status=entry.status,
                notes=entry.notes,
                recorded_by=actor.user_id,
                source="officer",
                created_at=utcnow(),
            )
            db.add(row)
            db.flush()
            created = True
        else:
            row.status = entry.status
            row.notes = entry.notes or row.notes
            row.recorded_by = actor.user_id
            created = False
        absence_id = None
        if entry.status == AttendanceStatus.absent and not _covers(db, student.student_id, day):
            existing = db.scalar(
                select(StudentAbsence.absence_id).where(
                    StudentAbsence.student_id == student.student_id,
                    StudentAbsence.absence_type == AbsenceType.unauthorized,
                    StudentAbsence.source == f"attendance:{row.record_id}",
                )
            )
            if existing is None:
                absence = StudentAbsence(
                    student_id=student.student_id,
                    absence_type=AbsenceType.unauthorized,
                    start_date=day,
                    end_date=None,
                    source=f"attendance:{row.record_id}",
                    notes="غياب غير مصرح مسجل من سجل الحضور اليومي.",
                )
                db.add(absence)
                db.flush()
                absence_id = absence.absence_id
        if created or absence_id:
            record_event(
                db,
                "attendance.record",
                actor=actor,
                target_id=student.user_id,
                details={
                    "attendance_record_id": row.record_id,
                    "student_id": student.student_id,
                    "absence_id": absence_id,
                    "date": day.isoformat(),
                    "status": entry.status.value,
                },
            )
        items.append(
            {
                "student_id": student.student_id,
                "status": entry.status,
                "created": created,
                "absence_id": absence_id,
            }
        )
    return {"record_date": day, "items": items}


def list_students(db, ctx, query=None, offset=0, limit=50):
    """Deterministic picker for attendance entry: housing only, id/name/major."""
    if ctx.user.role != RECORDER:
        raise AppError(403, "Housing Administration access required")
    base = select(Student)
    if query:
        like = "%" + query.strip() + "%"
        base = base.where(Student.full_name.like(like) | Student.university.like(like))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Student.full_name, Student.student_id).offset(offset).limit(limit)
    ).all()
    return {
        "items": [
            {
                "student_id": s.student_id,
                "full_name": s.full_name,
                "university": s.university,
                "major": s.major,
            }
            for s in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def list_daily(db, ctx, day, offset=0, limit=20):
    if ctx.user.role == R.student:
        raise AppError(403, "Housing Administration access required")
    query = select(AttendanceRecord).where(AttendanceRecord.record_date == day)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(AttendanceRecord.created_at, AttendanceRecord.record_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [_dict(db, r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def my_ledger(db, ctx, offset=0, limit=20):
    student = db.scalar(select(Student).where(Student.user_id == ctx.user.user_id))
    if student is None:
        raise AppError(404, "Student profile not found")
    query = select(AttendanceRecord).where(
        AttendanceRecord.student_id == student.student_id
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(AttendanceRecord.record_date.desc(), AttendanceRecord.record_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [_dict(db, r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def _dict(db, r) -> dict:
    return dict(
        record_id=r.record_id,
        student_id=r.student_id,
        student_name=_student_name(db, r.student_id),
        record_date=r.record_date,
        status=r.status,
        notes=r.notes,
        source=r.source,
        created_at=r.created_at,
    )
