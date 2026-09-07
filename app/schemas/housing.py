from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.enums import RoomAssignmentStatus, RoomStatus
from app.schemas.identity import StrictInput, UTCResponse

BuildingText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
FloorNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]
ApartmentNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]
RoomNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]


class FloorCreate(StrictInput):
    building_name: BuildingText
    floor_number: FloorNumber


class FloorResponse(UTCResponse):
    floor_id: str
    building_name: str
    floor_number: str


class ApartmentCreate(StrictInput):
    floor_id: str
    apartment_number: ApartmentNumber


class ApartmentResponse(UTCResponse):
    apartment_id: str
    floor_id: str
    building_name: str
    floor_number: str
    apartment_number: str


class RoomCreate(StrictInput):
    apartment_id: str
    room_number: RoomNumber
    capacity: int = Field(1, ge=1, le=10)


class RoomUpdate(StrictInput):
    room_number: RoomNumber | None = None
    capacity: int | None = Field(None, ge=1, le=10)
    status: RoomStatus | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not any(v is not None for v in (self.room_number, self.capacity, self.status)):
            raise ValueError("Provide at least one field to update.")
        return self


class RoomResponse(UTCResponse):
    room_id: str
    apartment_id: str
    building_name: str | None
    floor_number: str | None
    apartment_number: str | None
    room_number: str
    capacity: int
    status: RoomStatus
    occupancy: int


class RoomPage(BaseModel):
    items: list[RoomResponse]
    total: int
    offset: int
    limit: int


class AssignmentCreate(StrictInput):
    student_id: str
    room_id: str


class TransferInput(StrictInput):
    to_room_id: str


class AssignmentResponse(UTCResponse):
    assignment_id: str
    student_id: str
    student_name: str
    university: str
    room_id: str
    building_name: str
    floor_number: str
    apartment_number: str
    room_number: str
    capacity: int
    status: RoomAssignmentStatus
    assignment_date: datetime
    end_date: datetime | None
    room_status: RoomStatus
    occupancy: int


class AssignmentHistoryItem(UTCResponse):
    assignment_id: str
    room_number: str
    building_name: str
    floor_number: str
    apartment_number: str
    status: RoomAssignmentStatus
    assignment_date: datetime
    end_date: datetime | None


class MyAssignmentResponse(AssignmentResponse):
    history: list[AssignmentHistoryItem]


class AssignmentPage(BaseModel):
    items: list[AssignmentResponse]
    total: int
    offset: int
    limit: int


class EligibleStudent(UTCResponse):
    student_id: str
    full_name: str
    university: str
    major: str
    application_id: str
    application_date: datetime


class EligiblePage(BaseModel):
    items: list[EligibleStudent]
    total: int
    offset: int
    limit: int
