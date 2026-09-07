"""D7 daily attendance: bulk recording (Housing Administration) and the
student's own ledger."""

from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.schemas.daily_attendance import (
    AttendancePage,
    BulkResult,
    DailyBulkCreate,
    StudentLitePage,
)
from app.services import daily_attendance as service

router = APIRouter(tags=["Daily attendance"])


@router.post("/attendance/daily", response_model=BulkResult, status_code=201)
def record_daily(
    data: DailyBulkCreate, db: DatabaseSession, ctx: Authenticated
):
    return service.record_daily(db, ctx, data)


@router.get("/attendance/daily", response_model=AttendancePage)
def list_daily(
    db: DatabaseSession,
    ctx: Authenticated,
    record_date: date = Query(...),
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=100),
):
    return service.list_daily(db, ctx, record_date, offset, limit)


@router.get("/attendance/my-ledger", response_model=AttendancePage)
def my_ledger(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=100),
):
    return service.my_ledger(db, ctx, offset, limit)



@router.get("/attendance/students", response_model=StudentLitePage)
def list_students(
    db: DatabaseSession,
    ctx: Authenticated,
    q: str | None = Query(None, max_length=100),
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
):
    return service.list_students(db, ctx, q, offset, limit)
