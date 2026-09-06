"""Account policy approved for D2: system administrator only; self service is narrow."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from functools import wraps

from app.core.errors import AppError
from app.core.security import get_password_hash, verify_password
from app.models import AccountGuard, AuditEvent, User
from app.models.enums import UserRole
from app.services.audit import record_event
from app.services.sessions import lock_self, revoke_all, validate_locked_actor

ADMIN = UserRole.system_administrator


def account_write(operation):
    """Expose retryable DB conflicts safely; the outer UoW rolls back everything."""

    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except OperationalError as exc:
            if getattr(exc.orig, "args", (None,))[0] in {1020, 1205, 1213}:
                raise AppError(
                    409, "Concurrent account update; retry the request."
                ) from None
            raise

    return guarded


def require_admin(ctx):
    if ctx.user.must_change_password:
        raise AppError(403, "Password change required before this operation.")
    if ctx.user.role != ADMIN:
        raise AppError(403, "Operation not permitted")


def _guard(db):
    row = db.scalar(
        select(AccountGuard).where(AccountGuard.guard_id == 1).with_for_update()
    )
    if row is None:
        raise AppError(
            503, "Account administration is not initialized; apply migrations."
        )


def _flush(db):
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "args", (None,))[0] == 1062:
            raise AppError(409, "Username or email is already in use.") from None
        raise


def _admin_target(db, ctx, target_id=None):
    # Consistent order: global guard -> user rows -> sessions -> audit.
    _guard(db)
    ids = {ctx.user.user_id, target_id or ctx.user.user_id}
    users = {
        u.user_id: u
        for u in db.scalars(
            select(User)
            .where(User.user_id.in_(ids))
            .order_by(User.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    actor = users.get(ctx.user.user_id)
    validate_locked_actor(db, ctx, actor)
    if actor is None or actor.role != ADMIN:
        raise AppError(403, "Operation not permitted")
    if target_id is not None and target_id not in users:
        raise AppError(404, "User not found")
    return actor, users.get(target_id) if target_id is not None else None


@account_write
def bootstrap_admin(db, data):
    _guard(db)
    existing = db.scalar(
        select(User.user_id).where(User.role == ADMIN).limit(1).with_for_update()
    )
    if existing:
        raise AppError(
            409, "An administrator already exists; bootstrap is one-time only."
        )
    user = User(
        username=data.username,
        email=str(data.email),
        password_hash=get_password_hash(data.password),
        role=ADMIN,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    _flush(db)
    record_event(db, "account.bootstrap", actor=user, target_id=user.user_id)
    return user


@account_write
def create_account(db, ctx, data):
    actor, _ = _admin_target(db, ctx)
    user = User(
        username=data.username,
        email=str(data.email),
        password_hash=get_password_hash(data.password),
        role=data.role,
        is_active=data.is_active,
        must_change_password=True,
    )
    db.add(user)
    _flush(db)
    record_event(
        db,
        "account.create",
        actor=actor,
        target_id=user.user_id,
        details={"new_role": user.role.value, "is_active": user.is_active},
    )
    return user


def list_accounts(db, ctx, *, offset, limit):
    require_admin(ctx)
    items = list(
        db.scalars(
            select(User)
            .order_by(User.created_at, User.user_id)
            .offset(offset)
            .limit(limit)
        )
    )
    return dict(
        items=items,
        total=db.scalar(select(func.count()).select_from(User)),
        offset=offset,
        limit=limit,
    )


def read_account(db, ctx, user_id):
    require_admin(ctx)
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "User not found")
    return user


@account_write
def update_account(db, ctx, user_id, data):
    actor, target = _admin_target(db, ctx, user_id)
    changes = data.model_dump(exclude_unset=True)
    security_change = any(
        k in changes and changes[k] != getattr(target, k) for k in ("role", "is_active")
    )
    if target.user_id == actor.user_id and security_change:
        raise AppError(
            409, "Administrators cannot change their own role or activation state."
        )
    if (
        target.role == ADMIN
        and target.is_active
        and (
            changes.get("role", ADMIN) != ADMIN
            or changes.get("is_active", True) is False
        )
    ):
        # Locking read sees current committed state, not an earlier RR snapshot.
        active = list(
            db.scalars(
                select(User.user_id)
                .where(User.role == ADMIN, User.is_active.is_(True))
                .order_by(User.user_id)
                .with_for_update()
            )
        )
        if len(active) <= 1:
            raise AppError(409, "The last active administrator must be preserved.")
    old_role = target.role
    for name, value in changes.items():
        setattr(target, name, value)
    if security_change:
        revoke_all(db, target)
    _flush(db)
    if changes:
        record_event(
            db,
            "account.update",
            actor=actor,
            target_id=target.user_id,
            details={
                "changed_fields": sorted(changes),
                "old_role": old_role.value,
                "new_role": target.role.value,
                "is_active": target.is_active,
            },
        )
    return target


@account_write
def update_self(db, ctx, data):
    user = lock_self(db, ctx)
    changes = data.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(user, name, value)
    _flush(db)
    if changes:
        record_event(
            db,
            "profile.update",
            actor=user,
            target_id=user.user_id,
            details={"changed_fields": sorted(changes)},
        )
    return user


@account_write
def change_password(db, ctx, data):
    user = lock_self(db, ctx, ready=False)
    if not verify_password(data.current_password, user.password_hash):
        raise AppError(400, "Current password is incorrect.")
    if verify_password(data.new_password, user.password_hash):
        raise AppError(422, "Choose a different new password.")
    user.password_hash = get_password_hash(data.new_password)
    user.must_change_password = False
    revoke_all(db, user)
    record_event(db, "password.change", actor=user, target_id=user.user_id)


@account_write
def reset_password(db, ctx, user_id, data):
    actor, target = _admin_target(db, ctx, user_id)
    if actor.user_id == target.user_id:
        raise AppError(
            409, "Use the current-password change endpoint for your own account."
        )
    target.password_hash = get_password_hash(data.new_password)
    target.must_change_password = True
    revoke_all(db, target)
    record_event(db, "password.admin_reset", actor=actor, target_id=target.user_id)


def list_audit(db, ctx, *, offset, limit):
    require_admin(ctx)
    items = list(
        db.scalars(
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.event_id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return dict(
        items=items,
        total=db.scalar(select(func.count()).select_from(AuditEvent)),
        offset=offset,
        limit=limit,
    )
