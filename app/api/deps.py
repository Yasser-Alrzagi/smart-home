from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.database import DatabaseSession
from app.models.enums import UserRole
from app.models.user import User
from app.services.sessions import AuthContext, resolve_context

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token"
)


def get_auth_context(
    db: DatabaseSession, token: str = Depends(reusable_oauth2)
) -> AuthContext:
    return resolve_context(db, token)


Authenticated = Annotated[AuthContext, Depends(get_auth_context)]


def get_current_user(
    db: DatabaseSession, token: str = Depends(reusable_oauth2)
) -> User:
    return resolve_context(db, token).user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(
            401,
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


def get_current_ready_user(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if current_user.must_change_password:
        raise HTTPException(403, "Password change required before this operation.")
    return current_user


class RoleChecker:
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_ready_user)) -> User:
        if user.role not in self.allowed_roles:
            raise HTTPException(403, "Operation not permitted")
        return user
