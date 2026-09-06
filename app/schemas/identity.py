from datetime import datetime, timezone
import json
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from app.core.password_policy import validate_password_bounds
from app.models.enums import UserRole
from app.schemas.user import Email, NewPassword, UserCreate, UserResponse, Username

CurrentPassword = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        json_schema_extra={"writeOnly": True, "format": "password"},
    ),
    AfterValidator(validate_password_bounds),
]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SelfProfileUpdate(StrictInput):
    username: Username | None = None
    email: Email | None = None

    @field_validator("*", mode="before")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Omit a field to leave it unchanged; null is not allowed.")
        return value


class AdminAccountUpdate(SelfProfileUpdate):
    role: UserRole | None = None
    is_active: bool | None = None


class AdminAccountCreate(UserCreate):
    pass


class PasswordChange(StrictInput):
    current_password: CurrentPassword = Field(repr=False)
    new_password: NewPassword = Field(repr=False)


class PasswordReset(StrictInput):
    new_password: NewPassword = Field(repr=False)


class BootstrapAdmin(StrictInput):
    username: Username
    email: Email
    password: NewPassword = Field(repr=False)


class UserPage(BaseModel):
    items: list[UserResponse]
    total: int
    offset: int
    limit: int


class UTCResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer(
        "created_at",
        "expires_at",
        "revoked_at",
        "updated_at",
        "application_date",
        "submitted_at",
        "decision_date",
        "review_completed_at",
        check_fields=False,
    )
    def utc_dates(self, value):
        return (
            None
            if value is None
            else value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        )


class SessionResponse(UTCResponse):
    session_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class AuditResponse(UTCResponse):
    event_id: str
    actor_id: str | None
    target_user_id: str | None
    actor_role: str | None
    action: str
    details: dict
    created_at: datetime

    @field_validator("details", mode="before")
    @classmethod
    def parse_details(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class AuditPage(BaseModel):
    items: list[AuditResponse]
    total: int
    offset: int
    limit: int
