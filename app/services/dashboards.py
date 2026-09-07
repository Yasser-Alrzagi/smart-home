"""D8 role-scoped dashboard summaries.

Read-only counts and the latest items each role is responsible for,
computed with the same fixed RBAC matrix used everywhere else. No write,
no audit event — nothing to log.
"""

from datetime import datetime

from sqlalchemy import func, select

from app.models import (
    Application,
    AttendanceRecord,
    AuthSession,
    CleaningAssignment,
    CleaningCycle,
    Complaint,
    EmergencyReport,
    MaintenanceRequest,
    Notification,
    PermissionRequest,
    Room,
    RoomAssignment,
    Service,
    ServicePeriod,
    ServiceRegistration,
    Student,
    StudentAbsence,
    User,
)
from app.models.enums import (
    ApplicationStatus as S,
    AttendanceStatus,
    CleaningAssignmentStatus,
    CleaningCycleStatus,
    ComplaintStatus,
    EmergencyReportStatus,
    MaintenanceStatus,
    NotificationStatus,
    PermissionStatus,
    RoomAssignmentStatus,
    ServicePeriodStatus,
)

SERVICE_OFFICERS = {
    "Activity Officer",
    "Food Officer",
    "Sports Officer",
}


def _count(db, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def _stat(key, label, value):
    return {"key": key, "label": label, "value": int(value or 0)}


def _item(key, title, status, created_at):
    return {"key": key, "title": title, "status": status, "created_at": created_at}


def _student_of(db, user_id):
    return db.scalar(select(Student).where(Student.user_id == user_id))


def _student_name(db, student_id):
    student = db.get(Student, student_id)
    return student.full_name if student else "—"


def dashboard(db, ctx):
    builder = {
        "Student": _student_dashboard,
        "Student Affairs": _affairs_dashboard,
        "Housing Administration": _housing_dashboard,
        "Maintenance Officer": _maintenance_dashboard,
        "Activity Officer": _service_dashboard,
        "Food Officer": _service_dashboard,
        "Sports Officer": _service_dashboard,
        "Cleaning Officer": _cleaning_dashboard,
        "System Administrator": _admin_dashboard,
    }
    return builder[ctx.user.role.value](db, ctx.user)


# ---------------------------------------------------------------- student
def _student_dashboard(db, user):
    student = _student_of(db, user.user_id)
    if student is None:
        return {"role": "Student", "stats": [], "attention": [], "latest": [], "actions": []}
    sid = student.student_id
    unread = _count(
        db, select(Notification.notification_id).where(Notification.user_id == user.user_id,
                                                        Notification.status == NotificationStatus.unread)
    )
    absences = _count(db, select(StudentAbsence.absence_id).where(StudentAbsence.student_id == sid))
    applications = _count(db, select(Application.application_id).where(Application.student_id == sid))
    active_room = _count(
        db, select(RoomAssignment.assignment_id).where(RoomAssignment.student_id == sid,
                                                       RoomAssignment.status == RoomAssignmentStatus.active)
    )
    stats = [
        _stat("applications", "طلبات السكن", applications),
        _stat("absences", "الغياب الموثق", absences),
        _stat("unread", "الإشعارات غير المقروءة", unread),
        _stat("active_room", "سكن نشط", active_room),
    ]
    attention = []
    if unread:
        attention.append(_stat("unread", "إشعارات بانتظار القراءة", unread))
    pending_perm = _count(
        db, select(PermissionRequest.permission_id).where(
            PermissionRequest.student_id == sid,
            PermissionRequest.status == PermissionStatus.pending)
    )
    if pending_perm:
        attention.append(_stat("pending_permissions", "طلبات إذن قيد الموافقة", pending_perm))
    latest = []
    for app in db.scalars(
        select(Application).where(Application.student_id == sid)
        .order_by(Application.application_date.desc()).limit(3)
    ):
        latest.append(_item("application", "طلب سكن", app.status.value, app.application_date))
    for abs in db.scalars(
        select(StudentAbsence).where(StudentAbsence.student_id == sid)
        .order_by(StudentAbsence.start_date.desc()).limit(2)
    ):
        latest.append(_item("absence", "غياب: " + abs.absence_type.value, None, datetime.combine(abs.start_date, datetime.min.time())))
    latest.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    return {
        "role": "Student",
        "stats": stats,
        "attention": attention,
        "latest": latest[:5],
        "actions": [
            {"page": "applications", "label": "طلبات السكن"},
            {"page": "attendance", "label": "الغياب والإذن"},
            {"page": "services", "label": "الخدمات"},
        ],
    }


# ---------------------------------------------------------------- affairs
def _affairs_dashboard(db, user):
    under_review = _count(
        db, select(Application.application_id).where(
            Application.status.in_([S.submitted, S.under_review, S.pending_documents]))
    )
    pending_perm = _count(
        db, select(PermissionRequest.permission_id).where(PermissionRequest.status == PermissionStatus.pending)
    )
    pending_emerg = _count(
        db, select(EmergencyReport.report_id).where(
            EmergencyReport.status.in_([EmergencyReportStatus.reported, EmergencyReportStatus.under_review]))
    )
    stats = [
        _stat("under_review", "طلبات قيد المراجعة", under_review),
        _stat("pending_permissions", "طلبات إذن معلقة", pending_perm),
        _stat("pending_emergencies", "بلاغات طارئة معلقة", pending_emerg),
    ]
    attention = [s for s in stats if s["value"] > 0]
    latest = []
    for app in db.scalars(
        select(Application).order_by(Application.application_date.desc()).limit(3)
    ):
        latest.append(_item("application", "طلب: " + _student_name(db, app.student_id), app.status.value, app.application_date))
    for perm in db.scalars(
        select(PermissionRequest).order_by(PermissionRequest.start_date.desc()).limit(2)
    ):
        latest.append(_item("permission", "إذن غياب: " + _student_name(db, perm.student_id), perm.status.value,
                            datetime.combine(perm.start_date, datetime.min.time())))
    for rep in db.scalars(
        select(EmergencyReport).order_by(EmergencyReport.reported_at.desc()).limit(2)
    ):
        latest.append(_item("emergency", "بلاغ طارئ: " + _student_name(db, rep.student_id), rep.status.value, rep.reported_at))
    latest.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    return {
        "role": "Student Affairs",
        "stats": stats,
        "attention": attention,
        "latest": latest[:6],
        "actions": [
            {"page": "applications", "label": "مراجعة الطلبات"},
            {"page": "attendance", "label": "الموافقات والغياب"},
        ],
    }


# ---------------------------------------------------------------- housing
def _housing_dashboard(db, user):
    rooms_total = _count(db, select(Room.room_id))
    occupied = _count(
        db,
        select(RoomAssignment.room_id).where(RoomAssignment.status == RoomAssignmentStatus.active).distinct(),
    )
    active_exists = (
        select(RoomAssignment.assignment_id)
        .where(RoomAssignment.student_id == Student.student_id,
               RoomAssignment.status == RoomAssignmentStatus.active)
        .exists()
    )
    awaiting = _count(
        db,
        select(Application.application_id).join(Student, Application.student_id == Student.student_id)
        .where(Application.status == S.accepted, ~active_exists),
    )
    open_complaints = _count(
        db, select(Complaint.complaint_id).where(Complaint.status.in_([ComplaintStatus.open, ComplaintStatus.under_review]))
    )
    today = datetime.utcnow().date()
    today_absent = _count(
        db, select(AttendanceRecord.record_id).where(
            AttendanceRecord.record_date == today,
            AttendanceRecord.status == AttendanceStatus.absent)
    )
    ready = _count(db, select(Application.application_id).where(Application.status == S.ready_for_decision))
    stats = [
        _stat("rooms", "إجمالي الغرف", rooms_total),
        _stat("occupied", "غرف مشغولة", occupied),
        _stat("awaiting_assignment", "بانتظار غرفة", awaiting),
        _stat("open_complaints", "شكاوى مفتوحة", open_complaints),
        _stat("today_absent", "غائبون اليوم", today_absent),
    ]
    attention = []
    if ready:
        attention.append(_stat("ready", "طلبات بانتظار قرارك", ready))
    if awaiting:
        attention.append(_stat("awaiting_assignment", "طلبات بانتظار تسكين", awaiting))
    if open_complaints:
        attention.append(_stat("open_complaints", "شكاوى مفتوحة", open_complaints))
    if today_absent:
        attention.append(_stat("today_absent", "غائبون اليوم دون تغطية", today_absent))
    latest = []
    for rec in db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.record_date == today)
        .order_by(AttendanceRecord.created_at.desc()).limit(3)
    ):
        latest.append(_item("attendance", "حضور اليوم: " + _student_name(db, rec.student_id), rec.status.value, rec.created_at))
    for comp in db.scalars(
        select(Complaint).order_by(Complaint.created_at.desc()).limit(3)
    ):
        latest.append(_item("complaint", "شكوى: " + (comp.category or ""), comp.status.value, comp.created_at))
    for app in db.scalars(
        select(Application).where(Application.status == S.ready_for_decision)
        .order_by(Application.application_date.desc()).limit(3)
    ):
        latest.append(_item("application", "قرار: " + _student_name(db, app.student_id), app.status.value, app.application_date))
    latest.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    return {
        "role": "Housing Administration",
        "stats": stats,
        "attention": attention,
        "latest": latest[:6],
        "actions": [
            {"page": "housing", "label": "السكن والغرف"},
            {"page": "daily", "label": "الحضور اليومي"},
            {"page": "support", "label": "الشكاوى"},
            {"page": "applications", "label": "قرارات الطلبات"},
        ],
    }


# ---------------------------------------------------------------- maintenance
def _maintenance_dashboard(db, user):
    pending = _count(db, select(MaintenanceRequest.request_id).where(MaintenanceRequest.status == MaintenanceStatus.pending))
    assigned = _count(db, select(MaintenanceRequest.request_id).where(MaintenanceRequest.status == MaintenanceStatus.assigned))
    in_progress = _count(db, select(MaintenanceRequest.request_id).where(MaintenanceRequest.status == MaintenanceStatus.in_progress))
    open_total = _count(
        db, select(MaintenanceRequest.request_id).where(
            MaintenanceRequest.status.in_([MaintenanceStatus.pending, MaintenanceStatus.assigned, MaintenanceStatus.in_progress]))
    )
    stats = [
        _stat("pending", "بانتظار الإسناد", pending),
        _stat("assigned", "مُسندة", assigned),
        _stat("in_progress", "جاري التنفيذ", in_progress),
        _stat("open_total", "إجمالي المفتوحة", open_total),
    ]
    attention = [s for s in stats if s["key"] != "open_total" and s["value"] > 0]
    latest = []
    for req in db.scalars(
        select(MaintenanceRequest).order_by(MaintenanceRequest.created_at.desc()).limit(5)
    ):
        latest.append(_item("maintenance", req.problem_type or "طلب صيانة", req.status.value, req.created_at))
    return {
        "role": "Maintenance Officer",
        "stats": stats,
        "attention": attention,
        "latest": latest,
        "actions": [{"page": "support", "label": "طلبات الصيانة"}],
    }


# ---------------------------------------------------------------- service officers
def _service_dashboard(db, user):
    owned = select(Service.service_id).where(Service.managed_by_role == user.role)
    services = _count(db, owned)
    open_periods = _count(
        db, select(ServicePeriod.period_id).join(Service, ServicePeriod.service_id == Service.service_id)
        .where(Service.managed_by_role == user.role, ServicePeriod.status == ServicePeriodStatus.open)
    )
    upcoming = _count(
        db, select(ServicePeriod.period_id).join(Service, ServicePeriod.service_id == Service.service_id)
        .where(Service.managed_by_role == user.role, ServicePeriod.status == ServicePeriodStatus.upcoming)
    )
    registrations = _count(
        db, select(ServiceRegistration.registration_id)
        .join(ServicePeriod, ServiceRegistration.period_id == ServicePeriod.period_id)
        .join(Service, ServicePeriod.service_id == Service.service_id)
        .where(Service.managed_by_role == user.role)
    )
    stats = [
        _stat("services", "الخدمات", services),
        _stat("open_periods", "فترات مفتوحة للتسجيل", open_periods),
        _stat("upcoming", "فترات قادمة", upcoming),
        _stat("registrations", "إجمالي التسجيلات", registrations),
    ]
    attention = []
    if open_periods:
        attention.append(_stat("open_periods", "فترات مفتوحة للتسجيل", open_periods))
    if services == 0:
        attention.append(_stat("no_services", "لا خدمات بعد — أنشئ خدمة", 0))
    latest = []
    for period in db.scalars(
        select(ServicePeriod).join(Service, ServicePeriod.service_id == Service.service_id)
        .where(Service.managed_by_role == user.role)
        .order_by(ServicePeriod.start_date.desc()).limit(4)
    ):
        latest.append(_item("period", "فترة: " + (period.service.name if period.service else ""),
                            period.status.value,
                            datetime.combine(period.start_date, datetime.min.time())))
    for reg in db.scalars(
        select(ServiceRegistration).join(ServicePeriod, ServiceRegistration.period_id == ServicePeriod.period_id)
        .join(Service, ServicePeriod.service_id == Service.service_id)
        .where(Service.managed_by_role == user.role)
        .order_by(ServiceRegistration.registered_at.desc()).limit(3)
    ):
        latest.append(_item("registration", "تسجيل جديد", reg.status.value, reg.registered_at))
    latest.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    return {
        "role": user.role.value,
        "stats": stats,
        "attention": attention,
        "latest": latest[:5],
        "actions": [{"page": "services", "label": "إدارة الخدمات"}],
    }


# ---------------------------------------------------------------- cleaning
def _cleaning_dashboard(db, user):
    counts = {}
    for status in CleaningCycleStatus:
        counts[status.value] = _count(
            db, select(CleaningCycle.cycle_id).where(CleaningCycle.status == status)
        )
    pending_assign = _count(
        db, select(CleaningAssignment.assignment_id).where(
            CleaningAssignment.status == CleaningAssignmentStatus.pending)
    )
    stats = [
        _stat("cycles", "دورات النظافة", counts.get("draft", 0) + counts.get("optimizing", 0)
              + counts.get("pending_approval", 0) + counts.get("approved", 0)
              + counts.get("active", 0) + counts.get("completed", 0)),
        _stat("pending_approval", "بنتظار الموافقة", counts.get("pending_approval", 0)),
        _stat("active", "دورات نشطة", counts.get("active", 0)),
        _stat("pending_assign", "مهام بانتظار التنفيذ", pending_assign),
    ]
    attention = [s for s in stats if s["key"] != "cycles" and s["value"] > 0]
    latest = []
    for cycle in db.scalars(select(CleaningCycle).order_by(CleaningCycle.start_date.desc()).limit(5)):
        latest.append(_item("cycle", "دورة نظافة من " + str(cycle.start_date), cycle.status.value,
                            datetime.combine(cycle.start_date, datetime.min.time())))
    return {
        "role": "Cleaning Officer",
        "stats": stats,
        "attention": attention,
        "latest": latest,
        "actions": [{"page": "notifications", "label": "الإشعارات"}],
    }


# ---------------------------------------------------------------- admin
def _admin_dashboard(db, user):
    total_users = _count(db, select(User.user_id))
    active_users = _count(db, select(User.user_id).where(User.is_active.is_(True)))
    must_change = _count(db, select(User.user_id).where(User.must_change_password.is_(True)))
    sessions = _count(db, select(AuthSession.session_id).where(AuthSession.revoked_at.is_(None)))
    stats = [
        _stat("total_users", "إجمالي الحسابات", total_users),
        _stat("active_users", "حسابات نشطة", active_users),
        _stat("must_change", "بانتظار تغيير الكلمة", must_change),
        _stat("sessions", "جلسات نشطة", sessions),
    ]
    attention = []
    if must_change:
        attention.append(_stat("must_change", "حسابات لم تغيّر كلمتها", must_change))
    latest = []
    for u in db.scalars(select(User).order_by(User.created_at.desc()).limit(6)):
        latest.append(_item("user", u.username, u.role.value, u.created_at))
    return {
        "role": "System Administrator",
        "stats": stats,
        "attention": attention,
        "latest": latest,
        "actions": [
            {"page": "accounts", "label": "إدارة الحسابات"},
            {"page": "security", "label": "الأمان والجلسات"},
        ],
    }
