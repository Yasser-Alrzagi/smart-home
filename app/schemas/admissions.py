from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from app.models.enums import (
    AcademicStatus,
    ApplicationStatus,
    DocumentType,
    HousingStatus,
)
from app.schemas.identity import StrictInput, UTCResponse

ProfileText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
]


class ProfileCreate(StrictInput):
    full_name: ProfileText
    university: ProfileText
    major: ProfileText


class ProfileUpdate(ProfileCreate):
    expected_version: int = Field(ge=1)


class ProfileResponse(UTCResponse):
    student_id: str
    full_name: str
    university: str
    major: str
    academic_status: AcademicStatus
    housing_status: HousingStatus
    profile_version: int
    created_at: datetime
    updated_at: datetime


class VersionInput(StrictInput):
    expected_version: int = Field(ge=1)


class ReviewInput(VersionInput):
    action: Literal[
        "start", "request_documents", "complete", "return_to_review", "accept", "reject"
    ]
    note: str = Field("", max_length=2000)
    document_types: list[DocumentType] = Field(default_factory=list, max_length=6)


class DocumentResponse(UTCResponse):
    document_id: str
    document_type: DocumentType
    content_type: str | None
    size_bytes: int | None
    uploaded_at: datetime
    available: bool


class ApplicationSummary(UTCResponse):
    application_id: str
    student_id: str
    student_name: str
    university: str
    status: ApplicationStatus
    version: int
    application_date: datetime
    submitted_at: datetime | None


class EventResponse(UTCResponse):
    event_id: str
    action: str
    actor_role: str
    from_status: str | None
    to_status: str
    note: str | None
    application_version: int
    created_at: datetime


class ApplicationResponse(ApplicationSummary):
    profile_snapshot: dict | None
    review_notes: str | None
    requested_documents: list[DocumentType]
    decision_notes: str | None
    decision_date: datetime | None
    review_completed_at: datetime | None
    documents: list[DocumentResponse]
    history: list[EventResponse]


class ApplicationPage(BaseModel):
    items: list[ApplicationSummary]
    total: int
    offset: int
    limit: int


class EmptyApplicationInput(StrictInput):
    pass
