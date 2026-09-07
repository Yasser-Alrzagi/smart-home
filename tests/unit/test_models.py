"""Structural tests for the ORM layer (PHASE 3).

These tests read the mapped metadata only — they never touch MySQL, so they verify the
model definitions themselves rather than whatever happens to exist in the database.
"""
from datetime import datetime

import pytest
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import mysql

import app.models as models
from app.models.base import Base, utcnow

EXPECTED_TABLES = {
    "application_events",
    "account_guard", "auth_sessions", "audit_events", "login_rate_buckets",
    "users",
    "students",
    "student_status_history",
    "applications",
    "application_documents",
    "floors",
    "apartments",
    "rooms",
    "room_assignments",
    "complaints",
    "maintenance_requests",
    "cleaning_cycles",
    "cleaning_assignments",
    "ai_optimization_runs",
    "services",
    "service_periods",
    "service_registrations",
    "permission_requests",
    "student_absences",
    "emergency_reports",
    "disciplinary_cases",
    "notifications",
    "attendance_records",
}

# (table, column) -> referenced table, for the structural parents that must not be
# deleted while children exist.
RESTRICT_FOREIGN_KEYS = {
    ("apartments", "floor_id"): "floors",
    ("rooms", "apartment_id"): "apartments",
    ("cleaning_cycles", "floor_id"): "floors",
}

EXPECTED_UNIQUE_CONSTRAINTS = {
    "floors": ("uq_floors_building_number", {"building_name", "floor_number"}),
    "apartments": ("uq_apartments_floor_number", {"floor_id", "apartment_number"}),
    "service_registrations": (
        "uq_service_registrations_period_student",
        {"period_id", "student_id"},
    ),
    "attendance_records": (
        "uq_attendance_student_date",
        {"student_id", "record_date"},
    ),
}


def test_all_mappers_configure():
    """A wrong back_populates or a missing model only surfaces here, not at import."""
    configure_mappers()


def test_metadata_contains_exactly_the_expected_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert len(Base.metadata.tables) == 28


@pytest.mark.parametrize("name", sorted(models.__all__))
def test_every_exported_name_exists(name):
    assert getattr(models, name, None) is not None


@pytest.mark.parametrize(("table", "column", "parent"), [
    (table, column, parent)
    for (table, column), parent in RESTRICT_FOREIGN_KEYS.items()
])
def test_structural_parents_use_on_delete_restrict(table, column, parent):
    fks = [
        fk
        for fk in Base.metadata.tables[table].foreign_keys
        if fk.parent.name == column
    ]
    assert len(fks) == 1, f"{table}.{column} should have exactly one foreign key"
    fk = fks[0]
    assert fk.column.table.name == parent
    assert fk.ondelete == "RESTRICT"


@pytest.mark.parametrize("table", sorted(EXPECTED_UNIQUE_CONSTRAINTS))
def test_expected_unique_constraints_exist(table):
    expected_name, expected_columns = EXPECTED_UNIQUE_CONSTRAINTS[table]
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in Base.metadata.tables[table].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert expected_name in constraints
    assert constraints[expected_name] == expected_columns


def test_owned_children_cascade_on_student_delete():
    """Every student-owned table must drop its rows with the student."""
    owned = [
        "applications",
        "student_status_history",
        "room_assignments",
        "complaints",
        "maintenance_requests",
        "permission_requests",
        "student_absences",
        "emergency_reports",
        "service_registrations",
        "disciplinary_cases",
        "cleaning_assignments",
        "attendance_records",
    ]
    for table in owned:
        fks = [
            fk
            for fk in Base.metadata.tables[table].foreign_keys
            if fk.column.table.name == "students"
        ]
        assert fks, f"{table} has no foreign key to students"
        assert all(fk.ondelete == "CASCADE" for fk in fks), table


def test_actor_references_are_set_null():
    """Deleting a staff account must never delete the records they touched."""
    actor_columns = {
        ("applications", "reviewed_by"),
        ("student_status_history", "changed_by"),
        ("room_assignments", "assigned_by"),
        ("complaints", "handled_by"),
        ("maintenance_requests", "handled_by"),
        ("cleaning_cycles", "created_by"),
        ("ai_optimization_runs", "approved_by"),
        ("permission_requests", "reviewed_by"),
        ("emergency_reports", "handled_by"),
        ("disciplinary_cases", "decided_by"),
        ("attendance_records", "recorded_by"),
    }
    for table, column in actor_columns:
        fks = [
            fk
            for fk in Base.metadata.tables[table].foreign_keys
            if fk.parent.name == column
        ]
        assert len(fks) == 1, f"{table}.{column}"
        assert fks[0].column.table.name == "users"
        assert fks[0].ondelete == "SET NULL", f"{table}.{column}"


def test_emergency_report_absence_is_optional():
    """Rule: not every emergency report implies an absence."""
    column = Base.metadata.tables["emergency_reports"].c.absence_id
    assert column.nullable is True
    fk = next(iter(column.foreign_keys))
    assert fk.column.table.name == "student_absences"
    assert fk.ondelete == "SET NULL"


def test_utcnow_is_naive_utc():
    """Naive value required: the DATETIME columns are naive and PyMySQL drops offsets."""
    value = utcnow()
    assert isinstance(value, datetime)
    assert value.tzinfo is None


def test_datetime_defaults_use_the_shared_helper():
    """No model may reintroduce a timezone-aware default."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            default = column.default
            if default is None or not default.is_callable:
                continue
            produced = default.arg({})
            if isinstance(produced, datetime):
                assert produced.tzinfo is None, f"{table.name}.{column.name}"


def test_ddl_compiles_for_mysql():
    dialect = mysql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert table.name in ddl
