from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.database import DatabaseSession
from app.models.enums import UserRole
from app.models.user import User
from app.services.sessions import AuthContext, resolve_context

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login/access-token",
    auto_error=False,
)


def get_bearer_token(request: Request, token: str | None = Depends(reusable_oauth2)) -> str:
    """Extract the access token for API authentication.

    The primary channel is the standard ``Authorization: Bearer`` header. Some
    reverse proxies (notably the sandbox preview proxy) strip that header, so a
    secondary channel — ``X-Auth-Token`` — is accepted as a fallback. It is
    only read when the Authorization header is absent, never overwrites it.
    """
    if token:
        return token
    alt = request.headers.get("x-auth-token", "")
    if alt:
        return alt
    raise HTTPException(
        401,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_auth_context(
    db: DatabaseSession, token: str = Depends(get_bearer_token)
) -> AuthContext:
    return resolve_context(db, token)


Authenticated = Annotated[AuthContext, Depends(get_auth_context)]


def get_current_user(db: DatabaseSession, token: str = Depends(get_bearer_token)) -> User:
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
