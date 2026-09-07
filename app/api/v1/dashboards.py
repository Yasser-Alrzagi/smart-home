"""D8 role-scoped dashboard summary for the portal."""

from fastapi import APIRouter

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.schemas.dashboards import DashboardResponse
from app.services import dashboards as service

router = APIRouter(tags=["Dashboards"])


@router.get("/dashboards/me", response_model=DashboardResponse)
def my_dashboard(db: DatabaseSession, ctx: Authenticated):
    return service.dashboard(db, ctx)
