"""D2 identity storage. No cascaded deletion of security history."""

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)

from sqlalchemy.dialects.mysql import DATETIME

from app.models.base import Base, utcnow


class AccountGuard(Base):
    """Singleton row serializes bootstrap and role/activation administration."""

    __tablename__ = "account_guard"
    __table_args__ = (
        CheckConstraint("guard_id = 1", name="ck_account_guard_singleton"),
    )
    guard_id = Column(Integer, primary_key=True, autoincrement=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("token_version >= 0", name="ck_auth_sessions_version"),
        Index("ix_auth_sessions_active", "user_id", "revoked_at", "expires_at"),
    )
    session_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    token_version = Column(Integer, nullable=False)
    created_at = Column(DATETIME(fsp=6), nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    event_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id = Column(
        String(36),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    target_user_id = Column(
        String(36),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_role = Column(String(60), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    details = Column(Text, nullable=False, default="{}")
    created_at = Column(DATETIME(fsp=6), nullable=False, default=utcnow, index=True)


@event.listens_for(AuditEvent, "before_update")
@event.listens_for(AuditEvent, "before_delete")
def reject_audit_mutation(mapper, connection, target):
    raise ValueError("Audit events are append-only through the ORM.")


class LoginRateBucket(Base):
    __tablename__ = "login_rate_buckets"
    __table_args__ = (CheckConstraint("attempts >= 0", name="ck_login_rate_attempts"),)
    bucket_key = Column(String(64), primary_key=True)
    window_start = Column(BigInteger, primary_key=True)
    attempts = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
