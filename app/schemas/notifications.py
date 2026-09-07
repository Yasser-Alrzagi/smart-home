"""Notification schemas: read-only for the owner, no content writes by clients."""

from datetime import datetime

from pydantic import BaseModel

from app.models.enums import NotificationStatus
from app.schemas.identity import UTCResponse


class NotificationResponse(UTCResponse):
    notification_id: str
    title: str
    message: str
    status: NotificationStatus
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    total: int
    offset: int
    limit: int


class UnreadCount(BaseModel):
    unread: int
