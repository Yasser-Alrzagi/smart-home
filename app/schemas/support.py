from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.models.enums import ComplaintStatus, MaintenanceStatus
from app.schemas.identity import StrictInput, UTCResponse

CategoryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)
]
DescriptionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]
ResolvedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]


class ComplaintCreate(StrictInput):
    category: CategoryText
    description: DescriptionText


class ComplaintAction(StrictInput):
    action: Literal["start", "resolve", "close"]
    resolution: ResolvedText | None = None


class ComplaintResponse(UTCResponse):
    complaint_id: str
    student_id: str
    student_name: str | None
    university: str | None
    category: str
    description: str
    status: ComplaintStatus
    resolution: str | None
    created_at: datetime
    updated_at: datetime


class ComplaintPage(BaseModel):
    items: list[ComplaintResponse]
    total: int
    offset: int
    limit: int


class MaintenanceCreate(StrictInput):
    room_id: str | None = None
    problem_type: CategoryText
    description: DescriptionText


class MaintenanceAction(StrictInput):
    action: Literal["assign", "progress", "resolve", "close"]
    resolution: ResolvedText | None = None


class MaintenanceResponse(UTCResponse):
    request_id: str
    student_id: str
    student_name: str | None
    university: str | None
    room_id: str | None
    building_name: str | None
    floor_number: str | None
    apartment_number: str | None
    room_number: str | None
    problem_type: str
    description: str
    status: MaintenanceStatus
    resolution: str | None
    created_at: datetime
    updated_at: datetime


class MaintenancePage(BaseModel):
    items: list[MaintenanceResponse]
    total: int
    offset: int
    limit: int
