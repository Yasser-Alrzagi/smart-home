import uuid

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.models.enums import ComplaintStatus, MaintenanceStatus
from app.schemas.support import (
    ComplaintAction,
    ComplaintCreate,
    ComplaintPage,
    ComplaintResponse,
    MaintenanceAction,
    MaintenanceCreate,
    MaintenancePage,
    MaintenanceResponse,
)
from app.services import support as service

router = APIRouter(tags=["Complaints & maintenance"])


@router.get("/complaints/my", response_model=ComplaintPage)
def my_complaints(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.my_complaints(db, ctx, offset, limit)


@router.post("/complaints", response_model=ComplaintResponse, status_code=201)
def create_complaint(data: ComplaintCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_complaint(db, ctx, data)


@router.get("/complaints", response_model=ComplaintPage)
def complaints(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: ComplaintStatus | None = None,
):
    return service.list_complaints(db, ctx, status, offset, limit)


@router.post("/complaints/{complaint_id}/action", response_model=ComplaintResponse)
def action_complaint(
    complaint_id: uuid.UUID,
    data: ComplaintAction,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.update_complaint(db, ctx, str(complaint_id), data.action, data.resolution)


@router.get("/maintenance/my", response_model=MaintenancePage)
def my_maintenance(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.my_maintenance(db, ctx, offset, limit)


@router.post("/maintenance", response_model=MaintenanceResponse, status_code=201)
def create_maintenance(
    data: MaintenanceCreate, db: DatabaseSession, ctx: Authenticated
):
    return service.create_maintenance(db, ctx, data)


@router.get("/maintenance", response_model=MaintenancePage)
def maintenance(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: MaintenanceStatus | None = None,
):
    return service.list_maintenance(db, ctx, status, offset, limit)


@router.post("/maintenance/{request_id}/action", response_model=MaintenanceResponse)
def action_maintenance(
    request_id: uuid.UUID,
    data: MaintenanceAction,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.update_maintenance(db, ctx, str(request_id), data.action, data.resolution)
