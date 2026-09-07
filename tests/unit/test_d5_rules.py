"""Pure D5 rules: role remits and state machine tables, no database."""

from app.models.enums import (
    ComplaintStatus,
    EmergencyReportStatus,
    MaintenanceStatus,
    PermissionStatus,
    ServicePeriodStatus,
    ServiceType,
    UserRole,
)
from app.services.attendance import (
    EMERGENCY_TRANSITIONS,
    PERMISSION_TRANSITIONS,
    REVIEWER,
)
from app.services.facilities import PERIOD_TRANSITIONS, TYPE_FOR_ROLE
from app.services.support import (
    COMPLAINT_HANDLER,
    COMPLAINT_TRANSITIONS,
    MAINTENANCE_HANDLER,
    MAINTENANCE_TRANSITIONS,
)


def test_role_remit_is_complete_and_disjoint():
    owned = {role: types for role, types in TYPE_FOR_ROLE.items()}
    assert set(owned) == {
        UserRole.activity_officer,
        UserRole.food_officer,
        UserRole.sports_officer,
    }
    # Internet is owned by the activity officer; every type is claimed once.
    assert ServiceType.activity in TYPE_FOR_ROLE[UserRole.activity_officer]
    assert ServiceType.internet in TYPE_FOR_ROLE[UserRole.activity_officer]
    assert ServiceType.food in TYPE_FOR_ROLE[UserRole.food_officer]
    assert ServiceType.sports in TYPE_FOR_ROLE[UserRole.sports_officer]
    claimed = set().union(*TYPE_FOR_ROLE.values())
    assert claimed == set(ServiceType)


def test_period_state_machine():
    assert ServicePeriodStatus.completed not in PERIOD_TRANSITIONS[
        ServicePeriodStatus.completed
    ]
    assert ServicePeriodStatus.open in PERIOD_TRANSITIONS[ServicePeriodStatus.upcoming]
    assert ServicePeriodStatus.completed in PERIOD_TRANSITIONS[ServicePeriodStatus.closed]
    # closed may reopen; open may close; upcoming/completed are not reverted
    assert ServicePeriodStatus.open in PERIOD_TRANSITIONS[ServicePeriodStatus.closed]
    assert ServicePeriodStatus.closed in PERIOD_TRANSITIONS[ServicePeriodStatus.open]
    assert ServicePeriodStatus.upcoming not in PERIOD_TRANSITIONS[ServicePeriodStatus.closed]


def test_complaint_state_machine():
    assert COMPLAINT_HANDLER == UserRole.housing_administration
    assert ComplaintStatus.under_review in COMPLAINT_TRANSITIONS[ComplaintStatus.open]
    assert ComplaintStatus.resolved in COMPLAINT_TRANSITIONS[ComplaintStatus.under_review]
    assert ComplaintStatus.closed in COMPLAINT_TRANSITIONS[ComplaintStatus.resolved]
    assert not COMPLAINT_TRANSITIONS[ComplaintStatus.closed]


def test_maintenance_state_machine():
    assert MAINTENANCE_HANDLER == UserRole.maintenance_officer
    allowed = MAINTENANCE_TRANSITIONS[MaintenanceStatus.assigned]
    assert MaintenanceStatus.in_progress in allowed
    assert MaintenanceStatus.resolved in allowed  # direct skip allowed
    assert MaintenanceStatus.closed in MAINTENANCE_TRANSITIONS[MaintenanceStatus.resolved]
    assert not MAINTENANCE_TRANSITIONS[MaintenanceStatus.closed]


def test_permission_state_machine():
    assert REVIEWER == UserRole.student_affairs
    allowed = PERMISSION_TRANSITIONS[PermissionStatus.pending]
    assert {PermissionStatus.approved, PermissionStatus.rejected, PermissionStatus.cancelled} <= allowed
    assert not PERMISSION_TRANSITIONS[PermissionStatus.approved]


def test_emergency_state_machine():
    assert EmergencyReportStatus.under_review in EMERGENCY_TRANSITIONS[
        EmergencyReportStatus.reported
    ]
    assert EmergencyReportStatus.verified in EMERGENCY_TRANSITIONS[
        EmergencyReportStatus.under_review
    ]
    assert EmergencyReportStatus.closed in EMERGENCY_TRANSITIONS[
        EmergencyReportStatus.verified
    ]
    assert not EMERGENCY_TRANSITIONS[EmergencyReportStatus.closed]
