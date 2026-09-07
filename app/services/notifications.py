"""D6 policy: notifications are records of events, owned by their recipient.

- Notifications are created inside the same transaction as the event they
  describe (registration, complaint/maintenance action, permission decision,
  emergency verification). A failed business operation never leaves a
  notification behind.
- Recipients read their own mailbox only; marking another user's notification
  read is refused (404, never revealing existence).
- There is no public registration and notifications cannot be created,
  edited or deleted through the API.
- ``notify_user`` targets one user, ``notify_role`` targets every active user
  holding a role (used to reach officers) excluding the acting user.
"""

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import Notification, User, utcnow
from app.models.enums import NotificationStatus
from app.services.audit import record_event


def notify_user(db, *, user_id, title, message) -> None:
    """Add an unread notification for one user (same transaction as caller)."""
    db.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
            status=NotificationStatus.unread,
            created_at=utcnow(),
        )
    )
    db.flush()


def notify_role(db, role, title, message, *, exclude_user_id=None) -> int:
    """Notify every active holder of ``role`` except the acting user.

    Returns how many notifications were created (0 is fine: no officer yet).
    """
    created = 0
    user_ids = db.scalars(
        select(User.user_id).where(
            User.role == role, User.is_active.is_(True)
        )
    ).all()
    for user_id in user_ids:
        if user_id == exclude_user_id:
            continue
        notify_user(
            db, user_id=user_id, title=title, message=message
        )
        created += 1
    return created


def my_notifications(db, ctx, offset=0, limit=20):
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == ctx.user.user_id)
        .order_by(Notification.created_at.desc(), Notification.notification_id)
        .offset(offset)
        .limit(limit)
    ).all()
    total = db.scalar(
        select(func.count(Notification.notification_id)).where(
            Notification.user_id == ctx.user.user_id
        )
    )
    return {
        "items": [_dict(n) for n in rows],
        "total": total or 0,
        "offset": offset,
        "limit": limit,
    }


def unread_count(db, ctx) -> int:
    return (
        db.scalar(
            select(func.count(Notification.notification_id)).where(
                Notification.user_id == ctx.user.user_id,
                Notification.status == NotificationStatus.unread,
            )
        )
        or 0
    )


def mark_read(db, ctx, notification_id) -> dict:
    n = db.scalar(
        select(Notification)
        .where(
            Notification.notification_id == notification_id,
            Notification.user_id == ctx.user.user_id,
        )
        .with_for_update()
    )
    if n is None:
        raise AppError(404, "Notification not found")
    if n.status == NotificationStatus.unread:
        n.status = NotificationStatus.read
        n.read_at = utcnow()
        record_event(
            db,
            "notification.read",
            actor=ctx.user,
            details={"notification_id": n.notification_id},
        )
        db.flush()
    return _dict(n)


def mark_all_read(db, ctx) -> int:
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.user_id == ctx.user.user_id,
            Notification.status == NotificationStatus.unread,
        )
        .with_for_update()
    ).all()
    for n in rows:
        n.status = NotificationStatus.read
        n.read_at = utcnow()
    if rows:
        record_event(
            db,
            "notification.read_all",
            actor=ctx.user,
            details={"count": len(rows)},
        )
        db.flush()
    return len(rows)


def _dict(n) -> dict:
    return dict(
        notification_id=n.notification_id,
        title=n.title,
        message=n.message,
        status=n.status,
        created_at=n.created_at,
        read_at=n.read_at,
    )
