from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.models.enums import AbsenceType, EmergencyReportStatus, PermissionStatus
from app.schemas.identity import StrictInput, UTCResponse

ReasonText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]
ReportText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]


class PermissionCreate(StrictInput):
    start_date: date
    end_date: date
    reason: ReasonText


class PermissionDecision(StrictInput):
    action: Literal["approve", "reject"]


class PermissionResponse(UTCResponse):
    permission_id: str
    student_id: str
    student_name: str | None
    status: PermissionStatus
    start_date: date
    end_date: date
    reason: str
    reviewed_by: str | None


class PermissionPage(BaseModel):
    items: list[PermissionResponse]
    total: int
    offset: int
    limit: int


class EmergencyCreate(StrictInput):
    description: ReportText


class EmergencyDecision(StrictInput):
    action: Literal["start", "verify", "close"]


class EmergencyResponse(UTCResponse):
    report_id: str
    student_id: str
    student_name: str | None
    reported_at: datetime
    description: str
    status: EmergencyReportStatus
    exit_verified: bool
    absence_id: str | None


class EmergencyPage(BaseModel):
    items: list[EmergencyResponse]
    total: int
    offset: int
    limit: int


class AbsenceResponse(UTCResponse):
    absence_id: str
    absence_type: AbsenceType
    student_id: str | None = None
    student_name: str | None = None
    start_date: date
    end_date: date | None
    source: str | None
    notes: str | None


class AbsencePage(BaseModel):
    items: list[AbsenceResponse]
    total: int
    offset: int
    limit: int
