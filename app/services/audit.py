"""Append-only security events, with a strict non-secret details allowlist."""

import json
from app.models import AuditEvent

ALLOWED_DETAILS = {
    "changed_fields",
    "application_id", "student_id", "document_id", "document_type", "version", "from_status", "to_status",
    "old_role",
    "new_role",
    "is_active",
    "session_id",
    "account_key",
    "source_key",
    "revoked_count",
    # D4 housing: identifiers and occupancy numbers only, never profile values.
    "floor_id",
    "apartment_id",
    "room_id",
    "assignment_id",
    "from_room_id",
    "to_room_id",
    "occupancy",
    "capacity",
    "room_status",
    # D5 facilities/support/attendance: identifiers and counts only.
    "service_id",
    "service_type",
    "period_id",
    "registration_id",
    "registration_count",
    "complaint_id",
    "maintenance_request_id",
    "permission_id",
    "emergency_report_id",
    "absence_id",
    # D6 notifications: identifiers and counts only.
    "notification_id",
    "count",
    "read",
    # D7 daily attendance: identifiers, date and status only.
    "attendance_record_id",
    "date",
    "status",
}


def record_event(db, action, *, actor=None, target_id=None, details=None):
    details = details or {}
    if set(details) - ALLOWED_DETAILS:
        raise ValueError(
            "Unsupported audit detail; secrets and profile values must not be logged."
        )
    event = AuditEvent(
        actor_id=actor.user_id if actor else None,
        actor_role=actor.role.value if actor else None,
        target_user_id=target_id,
        action=action,
        details=json.dumps(details, ensure_ascii=True, sort_keys=True),
    )
    db.add(event)
    db.flush()
    return event
