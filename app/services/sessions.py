from dataclasses import dataclass
from datetime import timedelta, timezone
import uuid

from sqlalchemy import select, update

from app.core.config import settings
from app.core.errors import AppError, unauthorized
from app.core.security import create_access_token, decode_access_token
from app.models import AuthSession, User, utcnow
from app.services.audit import record_event


@dataclass(frozen=True)
class AuthContext:
    user: User
    session_id: str
    token_version: int


def _session_valid(session, user, version):
    return bool(
        user
        and user.is_active
        and user.auth_version == version
        and session
        and session.user_id == user.user_id
        and session.token_version == version
        and session.revoked_at is None
        and session.expires_at > utcnow()
    )


def resolve_context(db, token):
    payload = decode_access_token(token)
    if payload is None:
        raise unauthorized()
    user = db.get(User, payload["sub"])
    session = db.get(AuthSession, payload["jti"])
    if not _session_valid(session, user, payload["ver"]):
        raise unauthorized()
    return AuthContext(user, session.session_id, payload["ver"])


def validate_locked_actor(db, ctx, user, *, ready=True):
    """Caller locks User first, then rechecks session/version against latest rows."""
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.session_id == ctx.session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not _session_valid(session, user, ctx.token_version):
        raise unauthorized()
    if ready and user.must_change_password:
        raise AppError(403, "Password change required before this operation.")


def issue_session(db, user):
    """Caller must own the User row lock; all session writes share its transaction."""
    now = utcnow()
    old = list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user.user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.created_at, AuthSession.session_id)
            .with_for_update()
        )
    )
    for session in old[: max(0, len(old) - settings.MAX_ACTIVE_SESSIONS + 1)]:
        session.revoked_at = now
        record_event(
            db,
            "session.limit_revoke",
            actor=user,
            target_id=user.user_id,
            details={"session_id": session.session_id},
        )
    sid = str(uuid.uuid4())
    expires = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    session = AuthSession(
        session_id=sid,
        user_id=user.user_id,
        token_version=user.auth_version,
        created_at=now,
        expires_at=expires,
    )
    db.add(session)
    db.flush()
    token = create_access_token(
        user.user_id,
        user.role.value,
        session_id=sid,
        token_version=user.auth_version,
        expires_at=expires.replace(tzinfo=timezone.utc),
    )
    return token


def revoke_all(db, user):
    user.auth_version += 1
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.flush()


def lock_self(db, ctx, *, ready=True):
    user = db.scalar(
        select(User)
        .where(User.user_id == ctx.user.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    validate_locked_actor(db, ctx, user, ready=ready)
    return user


def logout(db, ctx, *, all_sessions=False, session_id=None):
    user = lock_self(db, ctx, ready=False)
    if all_sessions:
        revoke_all(db, user)
        record_event(db, "session.logout_all", actor=user, target_id=user.user_id)
        return
    sid = session_id or ctx.session_id
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.session_id == sid, AuthSession.user_id == user.user_id)
        .with_for_update()
    )
    if session is None:
        raise AppError(404, "Session not found")
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        record_event(
            db,
            "session.logout",
            actor=user,
            target_id=user.user_id,
            details={"session_id": sid},
        )
