"""Report/export API — dual data formats: JSON and XML.

Advanced Programming requirement: the system must support JSON and XML.
One router serves both: ``?format=json`` (default) or ``?format=xml``.
Reports are read-only views over existing business services; they never
mutate state. Role guards mirror the portal's fixed RBAC matrix.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import Authenticated
from app.core.database import DatabaseSession
from app.models.enums import UserRole as R
from app.services import accounts, admissions, dashboards
from app.services.sessions import AuthContext

router = APIRouter(prefix="/reports", tags=["Reports / Export"])


def require_staff(ctx: Authenticated) -> AuthContext:
    """Reports expose staff-facing data; student scoping stays in the portal."""
    if ctx.user.role not in (
        R.system_administrator,
        R.student_affairs,
        R.housing_administration,
    ):
        raise HTTPException(403, "Operation not permitted")
    return ctx


Staff = Annotated[AuthContext, Depends(require_staff)]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _format_query() -> str:
    """Declare the ``format`` query parameter with a strict value set."""
    return Query("json", pattern="^(json|xml)$")


# ------------------------------------------------------------- XML helpers
def _element(parent: ET.Element, tag: str, value) -> ET.Element:
    """Recursively attach a value as a child element (dict/list/primitive)."""
    child = ET.SubElement(parent, tag)
    if isinstance(value, dict):
        for key, item in value.items():
            _element(child, str(key), item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _element(child, "item", item)
    elif value is None:
        child.text = ""
    else:
        child.text = str(value)
    return child


def _xml_response(report_type: str, payload: dict) -> Response:
    """Serialize a JSON-shaped payload to an XML document."""
    root = ET.Element("report")
    root.set("type", report_type)
    root.set("generated_at", _utcnow())
    meta = {k: v for k, v in payload.items() if k != "items"}
    for key, value in meta.items():
        root.set(key, str(value))
    for item in payload.get("items", []):
        _element(root, "item", item)
    body = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return Response(content=body, media_type="application/xml")


# ----------------------------------------------------------------- routes
@router.get("/overview")
def overview_report(db: DatabaseSession, ctx: Authenticated, format: str = _format_query()):
    """Role-scoped dashboard summary (same data the portal shows)."""
    data = dashboards.dashboard(db, ctx)
    payload = {"role": data["role"], "items": data.get("stats", [])}
    if format == "xml":
        return _xml_response("overview", payload)
    return {"format": "json", **payload, "generated_at": _utcnow()}


@router.get("/users")
def users_report(
    db: DatabaseSession,
    ctx: Authenticated,
    format: str = _format_query(),
):
    """Export the account directory — System Administrator only."""
    accounts.require_admin(ctx)
    page = accounts.list_accounts(db, ctx, offset=0, limit=100)
    items = [
        {
            "username": u.username,
            "email": u.email,
            "role": u.role.value,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else "",
        }
        for u in page["items"]
    ]
    payload = {"count": len(items), "total": page["total"], "items": items}
    if format == "xml":
        return _xml_response("users", payload)
    return {"format": "json", **payload, "generated_at": _utcnow()}


@router.get("/applications")
def applications_report(
    db: DatabaseSession,
    ctx: Staff,
    format: str = _format_query(),
):
    """Export housing applications — staff roles only (no student records)."""
    page = admissions.list_applications(db, ctx, offset=0, limit=50)
    items = [
        {
            "application_id": item.get("application_id", ""),
            "student_name": item.get("student_name", ""),
            "university": item.get("university", ""),
            "status": str(item.get("status", "")),
            "application_date": str(item.get("application_date", ""))[:19],
        }
        for item in page["items"]
    ]
    payload = {"count": len(items), "total": page["total"], "items": items}
    if format == "xml":
        return _xml_response("applications", payload)
    return {"format": "json", **payload, "generated_at": _utcnow()}
