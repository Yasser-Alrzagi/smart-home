from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
)

from app.core.password_policy import (
    MAX_PASSWORD_CHARS,
    MIN_NEW_PASSWORD_CHARS,
    validate_password_bounds,
)
from app.models.enums import UserRole

Username = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=80)
]
Email = Annotated[EmailStr, Field(max_length=255)]
NewPassword = Annotated[
    str,
    Field(
        min_length=MIN_NEW_PASSWORD_CHARS,
        max_length=MAX_PASSWORD_CHARS,
        json_schema_extra={"writeOnly": True, "format": "password"},
    ),
    AfterValidator(validate_password_bounds),
]


class UserBase(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: Username
    email: Email
    role: UserRole
    is_active: bool = True


class UserCreate(UserBase):
    # Internal/admin input, NOT a public self-registration permission contract.
    password: NewPassword = Field(repr=False)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: Username | None = None
    email: Email | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: NewPassword | None = Field(None, repr=False)

    @field_validator(
        "username", "email", "role", "is_active", "password", mode="before"
    )
    @classmethod
    def reject_explicit_null(cls, value):
        # Validators do not run for omitted defaults. Omission is a no-op; null
        # is NOT a request to clear a non-nullable DB column or password hash.
        if value is None:
            raise ValueError(
                "This field cannot be null; omit it to leave it unchanged."
            )
        return value


class UserResponse(UserBase):
    user_id: str
    created_at: datetime
    updated_at: datetime
    must_change_password: bool = False
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at")
    def utc_dates(self, value):
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class Token(BaseModel):
    access_token: str = Field(repr=False)
    token_type: str
    expires_in: int = 1800
    password_change_required: bool = False


class TokenPayload(BaseModel):
    sub: str | None = None
    role: str | None = None
