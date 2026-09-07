import uuid

from fastapi import APIRouter, Query

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.models.enums import ServiceType
from app.schemas.facilities import (
    PeriodCreate,
    PeriodResponse,
    PeriodStatusInput,
    RegistrationCreate,
    RegistrationPage,
    RegistrationResponse,
    ServiceCreate,
    ServiceResponse,
    ServiceUpdate,
)
from app.services import facilities as service

router = APIRouter(tags=["Services & registrations"])


@router.get("/services", response_model=list[ServiceResponse])
def services(db: DatabaseSession, ctx: Authenticated):
    return service.list_services(db, ctx)


@router.post("/services", response_model=ServiceResponse, status_code=201)
def create_service(data: ServiceCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_service(db, ctx, data)


@router.patch("/services/{service_id}", response_model=ServiceResponse)
def update_service(
    service_id: uuid.UUID,
    data: ServiceUpdate,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.update_service(db, ctx, str(service_id), data)


@router.get("/service-periods", response_model=list[PeriodResponse])
def periods(
    db: DatabaseSession,
    ctx: Authenticated,
    service_type: ServiceType | None = None,
):
    return service.visible_periods(db, ctx, service_type)


@router.post("/service-periods", response_model=PeriodResponse, status_code=201)
def create_period(data: PeriodCreate, db: DatabaseSession, ctx: Authenticated):
    return service.create_period(db, ctx, data)


@router.post("/service-periods/{period_id}/status", response_model=PeriodResponse)
def change_period_status(
    period_id: uuid.UUID,
    data: PeriodStatusInput,
    db: DatabaseSession,
    ctx: Authenticated,
):
    return service.change_period_status(db, ctx, str(period_id), data.status)


@router.get(
    "/service-periods/{period_id}/registrations", response_model=RegistrationPage
)
def registrations(
    period_id: uuid.UUID,
    db: DatabaseSession,
    ctx: Authenticated,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(20, ge=1, le=50),
):
    return service.list_registrations(
        db, ctx, str(period_id), offset, limit
    )


@router.post("/service-registrations", response_model=RegistrationResponse, status_code=201)
def register(data: RegistrationCreate, db: DatabaseSession, ctx: Authenticated):
    return service.register(db, ctx, data)


@router.get("/service-registrations/me", response_model=list[RegistrationResponse])
def my_registrations(db: DatabaseSession, ctx: Authenticated):
    return service.my_registrations(db, ctx)


@router.post(
    "/service-registrations/{registration_id}/cancel",
    response_model=RegistrationResponse,
)
def cancel_registration(
    registration_id: uuid.UUID, db: DatabaseSession, ctx: Authenticated
):
    return service.cancel_registration(db, ctx, str(registration_id))
