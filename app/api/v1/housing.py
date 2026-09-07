import uuid

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.models.enums import RoomAssignmentStatus, RoomStatus
from app.schemas.housing import (
    ApartmentCreate,
    ApartmentResponse,
    AssignmentCreate,
    AssignmentPage,
    AssignmentResponse,
    EligiblePage,
    FloorCreate,
    FloorResponse,
    MyAssignmentResponse,
    RoomCreate,
    RoomPage,
    RoomResponse,
    RoomUpdate,
    TransferInput,
)
from app.services import housing as service

router = APIRouter(tags=["Housing & rooms"])


@router.get("/housing/floors", response_model=list[FloorResponse])
def floors(db: DatabaseSession, ctx: Authenticated):
    return service.list_floors(db, ctx)


@router.post("/housing/floors", response_model=FloorResponse, status_code=201)
def create_floor(data: FloorCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_floor(db, ctx, data)


@router.get("/housing/apartments", response_model=list[ApartmentResponse])
def apartments(
    db: DatabaseSession,
    ctx: Authenticated,
    floor_id: uuid.UUID | None = None,
):
    return service.list_apartments(db, ctx, str(floor_id) if floor_id else None)


@router.post("/housing/apartments", response_model=ApartmentResponse, status_code=201)
def create_apartment(
    data: ApartmentCreate, db: DatabaseSession, ctx: Authenticated
):
    return service.create_apartment(db, ctx, data)


@router.get("/housing/rooms", response_model=RoomPage)
def rooms(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: RoomStatus | None = None,
    building: str | None = Query(None, min_length=1, max_length=100),
):
    return service.list_rooms(db, ctx, status, building, offset, limit)


@router.post("/housing/rooms", response_model=RoomResponse, status_code=201)
def create_room(data: RoomCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_room(db, ctx, data)


@router.patch("/housing/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: uuid.UUID,
    data: RoomUpdate,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.update_room(db, ctx, str(room_id), data)


@router.get("/housing/students/unassigned", response_model=EligiblePage)
def unassigned(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.eligible_students(db, ctx, offset, limit)


@router.get("/housing/assignments", response_model=AssignmentPage)
def assignments(
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
    status: RoomAssignmentStatus | None = None,
):
    return service.list_assignments(db, ctx, status, offset, limit)


@router.post("/housing/assignments", response_model=AssignmentResponse, status_code=201)
def allocate(data: AssignmentCreate, db: DatabaseSession, ctx: Authenticated):
    return service.allocate(db, ctx, data)


@router.post(
    "/housing/assignments/{assignment_id}/transfer",
    response_model=AssignmentResponse,
    status_code=201,
)
def transfer(
    assignment_id: uuid.UUID,
    data: TransferInput,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.transfer(db, ctx, str(assignment_id), data)


@router.post("/housing/assignments/{assignment_id}/end", response_model=AssignmentResponse)
def end_assignment(
    assignment_id: uuid.UUID, db: DatabaseSession, ctx: Authenticated
):
    return service.end_assignment(db, ctx, str(assignment_id))


@router.get("/housing/me", response_model=MyAssignmentResponse)
def my_room(db: DatabaseSession, ctx: Authenticated):
    return service.my_assignment(db, ctx)
