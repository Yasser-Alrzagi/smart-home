"""Notification mailbox: own messages only, mark-as-read without content writes."""

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.schemas.notifications import NotificationPage, UnreadCount
from app.services import notifications as service

router = APIRouter(tags=["Notifications"])


@router.get("/notifications/my", response_model=NotificationPage)
def my_notifications(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.my_notifications(db, ctx, offset, limit)


@router.get("/notifications/unread-count", response_model=UnreadCount)
def unread_count(db: DatabaseSession, ctx: Authenticated):
    return UnreadCount(unread=service.unread_count(db, ctx))


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: str, db: DatabaseSession, ctx: Authenticated
):
    return service.mark_read(db, ctx, notification_id)


@router.post("/notifications/read-all")
def mark_all_read(db: DatabaseSession, ctx: Authenticated):
    count = service.mark_all_read(db, ctx)
    return {"read": count}
