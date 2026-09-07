"""D8 officer dashboard contracts: role-scoped summary, one shape for all roles."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.identity import UTCResponse


class StatItem(UTCResponse):
    key: str
    label: str
    value: int


class LatestItem(UTCResponse):
    key: str
    title: str
    status: str | None = None
    created_at: datetime | None = None


class ActionItem(BaseModel):
    page: str
    label: str


class DashboardResponse(UTCResponse):
    role: str
    stats: list[StatItem]
    attention: list[StatItem]
    latest: list[LatestItem]
    actions: list[ActionItem]
