"""
SQLAlchemy ORM Models package.

All 26 tables are imported here so Alembic and ``Base.metadata`` can discover them.
Importing this package is the only supported way to populate the metadata; importing
a single model module leaves the relationship targets unresolved.
"""
from app.models.base import Base, utcnow                  # noqa: F401
from app.models.enums import *                            # noqa: F401, F403
from app.models.user import User                          # noqa: F401
from app.models.student import Student                    # noqa: F401
from app.models.application import Application, ApplicationDocument  # noqa: F401
from app.models.status_history import StudentStatusHistory           # noqa: F401
from app.models.room import Floor, Apartment, Room, RoomAssignment   # noqa: F401
from app.models.complaint import Complaint, MaintenanceRequest       # noqa: F401
from app.models.cleaning import CleaningCycle, CleaningAssignment, AIOptimizationRun  # noqa: F401
from app.models.service_catalog import (                  # noqa: F401
    Service,
    ServicePeriod,
    ServiceRegistration,
)
from app.models.services import (                         # noqa: F401
    PermissionRequest,
    StudentAbsence,
    EmergencyReport,
    DisciplinaryCase,
    Notification,
)

from app.models.identity import AccountGuard, AuthSession, AuditEvent, LoginRateBucket

__all__ = [
    "AccountGuard", "AuthSession", "AuditEvent", "LoginRateBucket",
    "Base",
    "utcnow",
    # Identity
    "User",
    "Student",
    "StudentStatusHistory",
    # Applications
    "Application",
    "ApplicationDocument",
    # Housing structure
    "Floor",
    "Apartment",
    "Room",
    "RoomAssignment",
    # Complaints & maintenance
    "Complaint",
    "MaintenanceRequest",
    # Cleaning AI
    "CleaningCycle",
    "CleaningAssignment",
    "AIOptimizationRun",
    # Services
    "Service",
    "ServicePeriod",
    "ServiceRegistration",
    # Permissions, absences, emergency, discipline, notifications
    "PermissionRequest",
    "StudentAbsence",
    "EmergencyReport",
    "DisciplinaryCase",
    "Notification",
]
