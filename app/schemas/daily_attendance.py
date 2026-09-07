"""Daily attendance schemas: officer bulk entry, owner/student read."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import AttendanceStatus
from app.schemas.identity import StrictInput, UTCResponse


class AttendanceEntry(StrictInput):
    student_id: str = Field(min_length=1, max_length=36)
    status: AttendanceStatus
    notes: str | None = Field(default=None, max_length=2000)


class DailyBulkCreate(StrictInput):
    record_date: date
    records: list[AttendanceEntry] = Field(min_length=1, max_length=200)


class AttendanceResponse(UTCResponse):
    record_id: str
    student_id: str
    student_name: str | None = None
    record_date: date
    status: AttendanceStatus
    notes: str | None
    source: str
    created_at: datetime | None = None


class AttendancePage(BaseModel):
    items: list[AttendanceResponse]
    total: int
    offset: int
    limit: int


class BulkResultItem(UTCResponse):
    student_id: str
    status: AttendanceStatus
    created: bool
    absence_id: str | None = None


class BulkResult(BaseModel):
    record_date: date
    items: list[BulkResultItem]


class StudentLite(UTCResponse):
    student_id: str
    full_name: str
    university: str | None = None
    major: str | None = None


class StudentLitePage(BaseModel):
    items: list[StudentLite]
    total: int
    offset: int
    limit: int
