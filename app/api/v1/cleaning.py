"""D9 cleaning AI: cycles, BFS/A* runs, approval and assignments."""

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.schemas.cleaning_d9 import (
    ApproveRequest,
    AssignmentAction,
    AssignmentPage,
    AssignmentResponse,
    CycleCreate,
    CycleDetailResponse,
    CyclePage,
    CycleResponse,
    OptimizeRequest,
    RunResponse,
)
from app.services import cleaning as service

router = APIRouter(tags=["Cleaning AI"])


@router.get("/cleaning/floors")
def floors(db: DatabaseSession, ctx: Authenticated):
    return service.list_floors(db, ctx)


@router.post("/cleaning/cycles", response_model=CycleResponse, status_code=201)
def create_cycle(data: CycleCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_cycle(db, ctx, data)


@router.get("/cleaning/cycles", response_model=CyclePage)
def list_cycles(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.list_cycles(db, ctx, offset, limit)


@router.get("/cleaning/cycles/{cycle_id}", response_model=CycleDetailResponse)
def get_cycle(cycle_id: str, db: DatabaseSession, ctx: Authenticated):
    return service.get_cycle(db, ctx, cycle_id)


@router.post("/cleaning/cycles/{cycle_id}/optimize", response_model=RunResponse, status_code=201)
def optimize_cycle(cycle_id: str, data: OptimizeRequest, db: DatabaseSession, ctx: Authenticated):
    return service.optimize_cycle(db, ctx, cycle_id, data.algorithm)


@router.post("/cleaning/cycles/{cycle_id}/approve", response_model=CycleResponse)
def approve_cycle(cycle_id: str, data: ApproveRequest, db: DatabaseSession, ctx: Authenticated):
    return service.approve_cycle(db, ctx, cycle_id, data.run_id)


@router.post("/cleaning/cycles/{cycle_id}/activate", response_model=CycleResponse)
def activate_cycle(cycle_id: str, db: DatabaseSession, ctx: Authenticated):
    return service.activate_cycle(db, ctx, cycle_id)


@router.post("/cleaning/cycles/{cycle_id}/complete", response_model=CycleResponse)
def complete_cycle(cycle_id: str, db: DatabaseSession, ctx: Authenticated):
    return service.complete_cycle(db, ctx, cycle_id)


@router.get("/cleaning/my", response_model=AssignmentPage)
def my_assignments(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
):
    return service.my_assignments(db, ctx, offset, limit)


@router.post("/cleaning/my/{assignment_id}", response_model=AssignmentResponse)
def student_update(
    assignment_id: str, data: AssignmentAction, db: DatabaseSession, ctx: Authenticated
):
    return service.student_update(db, ctx, assignment_id, data.action)


@router.post("/cleaning/assignments/{assignment_id}/skip", response_model=AssignmentResponse)
def skip_assignment(assignment_id: str, db: DatabaseSession, ctx: Authenticated):
    return service.skip_assignment(db, ctx, assignment_id)
