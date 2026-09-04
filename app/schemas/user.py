import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    email: str = Field(..., pattern=r"^[\w\.\+-]+@[\w\.-]+\.\w+$")
    role: UserRole
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=80)
    email: Optional[str] = Field(None, pattern=r"^[\w\.\+-]+@[\w\.-]+\.\w+$")
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


class UserResponse(UserBase):
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None
