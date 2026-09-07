"""D5 policy: officers own their services; students register within open periods.

Rules (documented in docs/services-d5.md):

- Each service is owned by one officer role. activity_officer manages Activity
  and Internet services, food_officer Food, sports_officer Sports; the owner
  role is stored in services.managed_by_role and enforced on every operation.
- A period belongs to one service. Lifecycle: upcoming -> open -> closed ->
  completed, with open/closed as the only reversible step (reopen allowed).
- A student registers only while the period is open, only once per period
  (unique constraint) and, when capacity is set, while seats remain. Capacity
  is checked under the period row lock; concurrent registrations cannot exceed
  it.
- A student may cancel an open-period registration; cancel starts by the
  student and is preserved in history. Officers never delete registrations.
- Students must have a profile and must not be suspended/terminated (the
  housing status is authoritative for service eligibility).
"""


from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.models import Service, ServicePeriod, ServiceRegistration, Student, utcnow
from app.models.enums import (
    HousingStatus,
    ServicePeriodStatus as P,
    ServiceRegistrationStatus as SR,
    ServiceType,
    UserRole as R,
)
from app.core.database import SessionLocal
from app.core.database import get_named_lock as get_lock, release_named_lock
from app.services.accounts import account_write
from app.services.audit import record_event
from app.services.sessions import lock_self

# service type -> roles allowed to own it
TYPE_FOR_ROLE = {
    R.activity_officer: {ServiceType.activity, ServiceType.internet},
    R.food_officer: {ServiceType.food},
    R.sports_officer: {ServiceType.sports},
}

PERIOD_TRANSITIONS = {
    P.upcoming: {P.open},
    P.open: {P.closed},
    P.closed: {P.open, P.completed},
    P.completed: set(),
}

FORBIDDEN = {HousingStatus.suspended, HousingStatus.terminated}


def ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role not in TYPE_FOR_ROLE:
        raise AppError(403, "Services officer access required")


def student_ready(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != R.student:
        raise AppError(403, "Student access required")


def _lock_actor(db, ctx):
    actor = lock_self(db, ctx)
    ready(ctx)
    return actor


def _service(db, service_id, *, lock=False):
    query = select(Service).where(Service.service_id == service_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    service = db.scalar(query)
    if service is None:
        raise AppError(404, "Service not found")
    return service


def _period(db, period_id, *, lock=False):
    query = select(ServicePeriod).where(ServicePeriod.period_id == period_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    period = db.scalar(query)
    if period is None:
        raise AppError(404, "Service period not found")
    return period


def _owned(db, ctx, service):
    """Officer owns the service and its type matches the officer's remit."""
    if service.managed_by_role != ctx.user.role or service.service_type not in TYPE_FOR_ROLE[
        ctx.user.role
    ]:
        raise AppError(403, "This service is not managed by your role")


def _count_registered(db, period_id, *, lock=False):
    query = select(func.count(ServiceRegistration.registration_id)).where(
        ServiceRegistration.period_id == period_id,
        ServiceRegistration.status == SR.registered,
    )
    if lock:
        # A locking read sees the latest committed rows (current read), so the
        # seat count stays correct even when the transaction's consistent
        # read view was fixed earlier by the auth layer (InnoDB REPEATABLE
        # READ). The next-key locks it takes also serialize the concurrent
        # registrations that follow.
        query = query.with_for_update()
    return db.scalar(query)


def _flush(db):
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "args", (None,))[0] == 1062:
            raise AppError(409, "Registration already exists for this period.") from None
        raise


def _service_dict(service):
    return dict(
        service_id=service.service_id,
        service_type=service.service_type,
        name=service.name,
        managed_by_role=service.managed_by_role,
        is_active=service.is_active,
    )


def _period_dict(db, period, seats=None):
    return dict(
        period_id=period.period_id,
        service_id=period.service_id,
        service_name=db.get(Service, period.service_id).name if period.service_id else None,
        start_date=period.start_date,
        end_date=period.end_date,
        capacity=period.capacity,
        status=period.status,
        seats=seats if seats is not None else _count_registered(db, period.period_id),
    )


def _registration_dict(db, registration):
    period = db.get(ServicePeriod, registration.period_id)
    service = db.get(Service, period.service_id) if period else None
    student = db.get(Student, registration.student_id)
    if period is None or service is None or student is None:
        raise AppError(404, "Registration not found")
    return dict(
        registration_id=registration.registration_id,
        student_id=student.student_id,
        student_name=student.full_name,
        period_id=period.period_id,
        service_id=service.service_id,
        service_type=service.service_type,
        service_name=service.name,
        start_date=period.start_date,
        end_date=period.end_date,
        status=registration.status,
        registered_at=registration.registered_at,
    )


# ---------------------------------------------------------------------------
# Officer: services and periods
# ---------------------------------------------------------------------------


def list_services(db, ctx):
    ready(ctx)
    rows = db.scalars(
        select(Service)
        .where(Service.managed_by_role == ctx.user.role)
        .order_by(Service.service_type, Service.name)
    )
    return [_service_dict(service) for service in rows]


@account_write
def create_service(db, ctx, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    if data.service_type not in TYPE_FOR_ROLE[actor.role]:
        raise AppError(422, "This service type is not managed by your role")
    if db.scalar(
        select(Service.service_id)
        .where(
            Service.name == data.name,
            Service.service_type == data.service_type,
        )
        .with_for_update()
    ):
        raise AppError(409, "A service with this name and type already exists.")
    service = Service(
        service_type=data.service_type,
        name=data.name,
        managed_by_role=actor.role,
        is_active=data.is_active,
    )
    db.add(service)
    _flush(db)
    record_event(
        db,
        "service.create",
        actor=actor,
        details={"service_id": service.service_id, "service_type": service.service_type.value},
    )
    return _service_dict(service)


@account_write
def update_service(db, ctx, service_id, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    service = _service(db, service_id, lock=True)
    _owned(db, ctx, service)
    changed = []
    if data.name is not None and data.name != service.name:
        service.name = data.name
        changed.append("name")
    if data.is_active is not None and data.is_active != service.is_active:
        service.is_active = data.is_active
        changed.append("is_active")
    _flush(db)
    record_event(
        db,
        "service.update",
        actor=actor,
        details={"service_id": service.service_id},
    )
    return _service_dict(service)


def visible_periods(db, ctx, service_type=None):
    """Students and officers both read periods; officers see all their services."""
    query = select(ServicePeriod, Service).join(
        Service, Service.service_id == ServicePeriod.service_id
    )
    if ctx.user.role in TYPE_FOR_ROLE:
        query = query.where(Service.managed_by_role == ctx.user.role)
    else:
        student_ready(ctx)
        query = query.where(Service.is_active.is_(True))
    if service_type is not None:
        query = query.where(Service.service_type == service_type)
    rows = db.execute(query.order_by(ServicePeriod.start_date.desc())).all()
    return [_period_dict(db, period) for period, service in rows]


@account_write
def create_period(db, ctx, data):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    service = _service(db, data.service_id, lock=True)
    _owned(db, ctx, service)
    if not service.is_active:
        raise AppError(409, "Service is inactive; periods cannot be added.")
    if data.start_date > data.end_date:
        raise AppError(422, "Period start must not be after its end.")
    period = ServicePeriod(
        service_id=service.service_id,
        start_date=data.start_date,
        end_date=data.end_date,
        capacity=data.capacity,
        status=P.upcoming,
    )
    db.add(period)
    _flush(db)
    record_event(
        db,
        "period.create",
        actor=actor,
        details={"service_id": service.service_id, "period_id": period.period_id},
    )
    return _period_dict(db, period)


@account_write
def change_period_status(db, ctx, period_id, status):
    ready(ctx)
    actor = _lock_actor(db, ctx)
    period = _period(db, period_id, lock=True)
    _owned(db, ctx, _service(db, period.service_id))
    allowed = PERIOD_TRANSITIONS[period.status]
    if status not in allowed:
        raise AppError(
            409,
            f"Period cannot move from {period.status.value} to {status.value}.",
        )
    previous = period.status
    period.status = status
    _flush(db)
    record_event(
        db,
        "period.status_change",
        actor=actor,
        details={
            "period_id": period.period_id,
            "from_status": previous.value,
            "to_status": status.value,
            "registration_count": _count_registered(db, period.period_id),
        },
    )
    return _period_dict(db, period)


def list_registrations(db, ctx, period_id, offset=0, limit=20):
    ready(ctx)
    period = _period(db, period_id)
    _owned(db, ctx, _service(db, period.service_id))
    query = (
        select(ServiceRegistration, Student)
        .join(Student, Student.student_id == ServiceRegistration.student_id)
        .where(ServiceRegistration.period_id == period_id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(ServiceRegistration.registered_at, ServiceRegistration.registration_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return dict(
        items=[
            dict(
                registration_id=registration.registration_id,
                student_id=student.student_id,
                student_name=student.full_name,
                university=student.university,
                status=registration.status,
                registered_at=registration.registered_at,
            )
            for registration, student in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Students: registrations
# ---------------------------------------------------------------------------


def my_registrations(db, ctx):
    student_ready(ctx)
    student = _my_student(db, ctx, check_status=False)
    rows = db.execute(
        select(ServiceRegistration)
        .where(ServiceRegistration.student_id == student.student_id)
        .order_by(ServiceRegistration.registered_at.desc())
    ).scalars()
    return [_registration_dict(db, registration) for registration in rows]


def _my_student(db, ctx, *, check_status=True):
    student_ready(ctx)
    student = db.scalar(select(Student).where(Student.user_id == ctx.user.user_id))
    if student is None:
        raise AppError(404, "Student profile not found")
    if check_status and student.housing_status in FORBIDDEN:
        raise AppError(409, "Service registration is not available in your current status.")
    return student


@account_write
def register(db, ctx, data):
    """Register a student in an open period.

    Runs in its own short transaction guarded by a server-side named lock
    (GET_LOCK), so concurrent registrations for the same period serialize:
    the second one waits until the first commits, then sees its registration
    and gets the 422 capacity response.

    Everything - including the actor/user row lock and the audit event - runs
    inside this transaction, because the outer request transaction holds its
    own user-row lock (lock_self in the auth layer) and a separate transaction
    writing rows that reference that user would wait on it forever.
    """
    student_ready(ctx)
    lock_name = f"service_register:{data.period_id}"
    tx = SessionLocal()
    try:
        with tx.begin():
            actor = lock_self(tx, ctx)
            student_ready(ctx)
            if not get_lock(tx, lock_name, timeout=15):
                raise AppError(409, "The period is busy; retry the request.")
            try:
                period = _period(tx, data.period_id, lock=True)
                student = _my_student(tx, ctx)
                service = _service(tx, period.service_id)
                if not service.is_active:
                    raise AppError(409, "The service is inactive.")
                if period.status != P.open:
                    raise AppError(409, "Registrations are only accepted while the period is open.")
                existing = tx.scalar(
                    select(ServiceRegistration.registration_id).where(
                        ServiceRegistration.period_id == period.period_id,
                        ServiceRegistration.student_id == student.student_id,
                    )
                )
                if existing is not None:
                    raise AppError(409, "You already have a registration for this period.")
                if period.capacity is not None:
                    seats = _count_registered(tx, period.period_id)
                    if seats >= period.capacity:
                        raise AppError(422, "The period is at full capacity.")
                registration = ServiceRegistration(
                    period_id=period.period_id,
                    student_id=student.student_id,
                    registered_at=utcnow(),
                    status=SR.registered,
                )
                tx.add(registration)
                _flush(tx)
                record_event(
                    tx,
                    "registration.create",
                    actor=actor,
                    target_id=student.user_id,
                    details={
                        "registration_id": registration.registration_id,
                        "period_id": period.period_id,
                        "registration_count": _count_registered(tx, period.period_id),
                    },
                )
                result = _registration_dict(tx, registration)
            finally:
                # MySQL server-side named locks are per-connection and survive
                # commit/rollback, so they must be released here, before the
                # transaction ends and the connection returns to the pool.
                # Any business error above (409/422) used to skip this release
                # and stranding the lock on the pooled connection, which made a
                # later registration for the same period wait 15s and fail with
                # "period busy". The period row lock (SELECT ... FOR UPDATE)
                # stays held until commit, so a concurrent registration that
                # grabs the named lock right after this release still blocks
                # on that row lock before counting seats -> capacity stays
                # correct.
                release_named_lock(tx, lock_name)
        return result
    finally:
        tx.close()


@account_write
def cancel_registration(db, ctx, registration_id):
    student_ready(ctx)
    actor = lock_self(db, ctx)
    student_ready(ctx)
    registration = db.scalar(
        select(ServiceRegistration)
        .where(ServiceRegistration.registration_id == registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if registration is None:
        raise AppError(404, "Registration not found")
    period = _period(db, registration.period_id, lock=True)
    student = _my_student(db, ctx, check_status=False)
    if registration.student_id != student.student_id:
        raise AppError(404, "Registration not found")
    if registration.status != SR.registered:
        raise AppError(409, "This registration is already cancelled.")
    if period.status != P.open:
        raise AppError(409, "Cancellation is only allowed while the period is open.")
    registration.status = SR.cancelled
    _flush(db)
    record_event(
        db,
        "registration.cancel",
        actor=actor,
        target_id=student.user_id,
        details={
            "registration_id": registration.registration_id,
            "period_id": period.period_id,
        },
    )
    return _registration_dict(db, registration)