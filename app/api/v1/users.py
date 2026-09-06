"""System-administrator account management only. No DELETE user operation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.schemas.identity import (
    AdminAccountCreate,
    AdminAccountUpdate,
    AuditPage,
    PasswordReset,
    UserPage,
)
from app.schemas.user import UserResponse
from app.services import accounts
from app.services.sessions import AuthContext

router = APIRouter(tags=["Account administration"])


def require_admin(ctx: Authenticated):
    accounts.require_admin(ctx)
    return ctx


Admin = Annotated[AuthContext, Depends(require_admin)]


@router.post("/users", response_model=UserResponse, status_code=201)
def create_user(data: AdminAccountCreate, db: DatabaseSession, ctx: Admin):
    return accounts.create_account(db, ctx, data)


@router.get("/users", response_model=UserPage)
def list_users(
    db: DatabaseSession,
    ctx: Admin,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
):
    return accounts.list_accounts(db, ctx, offset=offset, limit=limit)


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: uuid.UUID, db: DatabaseSession, ctx: Admin):
    return accounts.read_account(db, ctx, str(user_id))


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID, data: AdminAccountUpdate, db: DatabaseSession, ctx: Admin
):
    return accounts.update_account(db, ctx, str(user_id), data)


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: uuid.UUID, data: PasswordReset, db: DatabaseSession, ctx: Admin
):
    accounts.reset_password(db, ctx, str(user_id), data)
    return Response(status_code=204)


@router.get("/audit-events", response_model=AuditPage)
def list_audit(
    db: DatabaseSession,
    ctx: Admin,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
):
    return accounts.list_audit(db, ctx, offset=offset, limit=limit)
