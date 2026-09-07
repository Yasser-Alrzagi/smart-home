import uuid

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.models.enums import AbsenceType, EmergencyReportStatus, PermissionStatus
from app.schemas.attendance import (
    AbsencePage,
    EmergencyCreate,
    EmergencyDecision,
    EmergencyPage,
    EmergencyResponse,
    PermissionCreate,
    PermissionDecision,
    PermissionPage,
    PermissionResponse,
)
from app.services import attendance as service

router = APIRouter(tags=["Permissions & attendance"])


@router.get("/permissions/my", response_model=PermissionPage)
def my_permissions(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.my_permissions(db, ctx, offset, limit)


@router.post("/permissions", response_model=PermissionResponse, status_code=201)
def create_permission(
    data: PermissionCreate, db: DatabaseSession, ctx: Authenticated
):
    return service.create_permission(db, ctx, data)


@router.get("/permissions", response_model=PermissionPage)
def permissions(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: PermissionStatus | None = None,
):
    return service.list_permissions(db, ctx, status, offset, limit)


@router.post("/permissions/{permission_id}/decision", response_model=PermissionResponse)
def decide_permission(
    permission_id: uuid.UUID,
    data: PermissionDecision,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.review_permission(db, ctx, str(permission_id), data.action)


@router.post("/permissions/{permission_id}/cancel", response_model=PermissionResponse)
def cancel_permission(
    permission_id: uuid.UUID, db: DatabaseSession, ctx: Authenticated
):
    return service.cancel_permission(db, ctx, str(permission_id))


@router.get("/emergency/my", response_model=EmergencyPage)
def my_reports(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.my_reports(db, ctx, offset, limit)


@router.post("/emergency", response_model=EmergencyResponse, status_code=201)
def create_report(data: EmergencyCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_report(db, ctx, data)


@router.get("/emergency", response_model=EmergencyPage)
def reports(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: EmergencyReportStatus | None = None,
):
    return service.list_reports(db, ctx, status, offset, limit)


@router.post("/emergency/{report_id}/action", response_model=EmergencyResponse)
def action_report(
    report_id: uuid.UUID,
    data: EmergencyDecision,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.review_report(db, ctx, str(report_id), data.action)


@router.get("/absences/my", response_model=AbsencePage)
def my_absences(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.my_absences(db, ctx, offset, limit)


@router.get("/absences", response_model=AbsencePage)
def absences(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    absence_type: AbsenceType | None = None,
):
    return service.list_absences(db, ctx, absence_type, offset, limit)
