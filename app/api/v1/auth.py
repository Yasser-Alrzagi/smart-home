"""Authentication and narrowly scoped self-service. No public registration."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import Authenticated
from app.core.config import settings
from app.core.database import DatabaseSession
from app.core.errors import AppError
from app.core.password_policy import validate_password_bounds
from app.models import AuthSession, utcnow
from app.repositories.user import user_repo
from app.schemas.identity import PasswordChange, SelfProfileUpdate, SessionResponse
from app.schemas.user import Token, UserResponse
from app.services import accounts, sessions
from app.services.audit import record_event
from app.services.auth import auth_service
from app.services.rate_limit import (
    consume,
    limit_account,
    limit_ip,
    opaque_key,
    record_failed_login,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def bounded_login_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> OAuth2PasswordRequestForm:
    try:
        validate_password_bounds(form_data.password)
        if not 1 <= len(form_data.username) <= 80:
            raise ValueError("Invalid username length")
        form_data.username.encode("utf-8")
    except ValueError:
        raise HTTPException(
            422,
            "Invalid login input: username 1-80 characters, password 1-256 characters (valid UTF-8).",
        ) from None
    return form_data


def request_source(request):
    # Do not trust client-supplied X-Forwarded-For here. Configure trusted proxy
    # addresses in the ASGI server if a reverse proxy supplies request.client.
    return request.client.host if request.client else "unknown"


@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: DatabaseSession,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(bounded_login_form),
):
    source = request_source(request)
    limit_ip(source)
    found = user_repo.get_by_username(db, username=form_data.username)
    account_key = found.user_id if found else form_data.username.casefold()
    limit_account(source, account_key)
    user = auth_service.authenticate(
        db, username=form_data.username, password=form_data.password
    )
    if not user or not user.is_active:
        record_failed_login(source, account_key)
        raise AppError(
            401, "Incorrect username or password", {"WWW-Authenticate": "Bearer"}
        )
    token = sessions.issue_session(db, user)
    record_event(db, "login.success", actor=user, target_id=user.user_id)
    return Token(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        password_change_required=user.must_change_password,
    )


@router.get("/users/me", response_model=UserResponse)
def read_users_me(ctx: Authenticated):
    return ctx.user


@router.patch("/users/me", response_model=UserResponse)
def update_me(data: SelfProfileUpdate, db: DatabaseSession, ctx: Authenticated):
    return accounts.update_self(db, ctx, data)


@router.post("/change-password", status_code=204)
def change_password(
    data: PasswordChange, db: DatabaseSession, ctx: Authenticated, request: Request
):
    consume(
        opaque_key("password_change", request_source(request) + ":" + ctx.user.user_id),
        limit=5,
        seconds=300,
    )
    accounts.change_password(db, ctx, data)
    return Response(status_code=204)


@router.post("/logout", status_code=204)
def logout(db: DatabaseSession, ctx: Authenticated):
    sessions.logout(db, ctx)
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
def logout_all(db: DatabaseSession, ctx: Authenticated):
    sessions.logout(db, ctx, all_sessions=True)
    return Response(status_code=204)


@router.get("/sessions", response_model=list[SessionResponse])
def my_sessions(db: DatabaseSession, ctx: Authenticated):
    return list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == ctx.user.user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
            .order_by(AuthSession.created_at.desc(), AuthSession.session_id)
            .limit(settings.MAX_ACTIVE_SESSIONS)
        )
    )


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: uuid.UUID, db: DatabaseSession, ctx: Authenticated):
    sessions.logout(db, ctx, session_id=str(session_id))
    return Response(status_code=204)
