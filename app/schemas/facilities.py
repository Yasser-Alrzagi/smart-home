from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import (
    ServicePeriodStatus,
    ServiceRegistrationStatus,
    ServiceType,
    UserRole,
)
from app.schemas.identity import StrictInput, UTCResponse

ServiceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
]


class ServiceCreate(StrictInput):
    service_type: ServiceType
    name: ServiceName
    is_active: bool = True


class ServiceUpdate(StrictInput):
    name: ServiceName | None = None
    is_active: bool | None = None


class ServiceResponse(UTCResponse):
    service_id: str
    service_type: ServiceType
    name: str
    managed_by_role: UserRole
    is_active: bool


class PeriodCreate(StrictInput):
    service_id: str
    start_date: date
    end_date: date
    capacity: int | None = Field(None, ge=1, le=1000)


class PeriodStatusInput(StrictInput):
    status: ServicePeriodStatus


class PeriodResponse(UTCResponse):
    period_id: str
    service_id: str
    service_name: str | None
    start_date: date
    end_date: date
    capacity: int | None
    status: ServicePeriodStatus
    seats: int


class RegistrationCreate(StrictInput):
    period_id: str


class RegistrationResponse(UTCResponse):
    registration_id: str
    student_id: str
    student_name: str
    period_id: str
    service_id: str
    service_type: ServiceType
    service_name: str
    start_date: date
    end_date: date
    status: ServiceRegistrationStatus
    registered_at: datetime


class PeriodRegistration(UTCResponse):
    registration_id: str
    student_id: str
    student_name: str
    university: str
    status: ServiceRegistrationStatus
    registered_at: datetime


class RegistrationPage(BaseModel):
    items: list[PeriodRegistration]
    total: int
    offset: int
    limit: int
