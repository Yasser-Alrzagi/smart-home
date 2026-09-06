"""Verifies the schema actually present in MySQL matches the ORM models.

These are read-only queries against the database configured in .env. They fail — rather
than silently pass — if the applied migration drifted from the models, if a table landed
on the wrong storage engine (foreign keys are ignored outside InnoDB), or if a
collation other than utf8mb4_unicode_ci was inherited.
"""
import pytest
from sqlalchemy import inspect, text

from app.core.database import engine
from app.models import Base

from app.core.schema_version import SCHEMA_HEAD
EXPECTED_REVISION = SCHEMA_HEAD


@pytest.fixture(scope="module")
def connection():
    with engine.connect() as conn:
        yield conn


@pytest.fixture(scope="module")
def live_tables(connection):
    rows = connection.execute(
        text(
            "SELECT table_name, engine, table_collation "
            "FROM information_schema.tables WHERE table_schema = DATABASE()"
        )
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def test_alembic_version_records_the_expected_revision(connection):
    versions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == [EXPECTED_REVISION]


def test_all_model_tables_exist(live_tables):
    expected = set(Base.metadata.tables)
    assert len(expected) == 26
    assert expected <= set(live_tables), f"missing: {sorted(expected - set(live_tables))}"


def test_no_unexpected_tables(live_tables):
    extra = set(live_tables) - set(Base.metadata.tables) - {"alembic_version"}
    assert not extra


def test_every_table_is_innodb_with_utf8mb4(live_tables):
    """Foreign keys are silently ignored on MyISAM, so the engine is not cosmetic."""
    wrong = {
        name: props
        for name, props in live_tables.items()
        if props != ("InnoDB", "utf8mb4_unicode_ci")
    }
    assert not wrong


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_live_columns_match_the_model(table_name):
    inspector = inspect(engine)
    live = {column["name"]: column for column in inspector.get_columns(table_name)}
    model = Base.metadata.tables[table_name]

    assert set(live) == set(model.columns.keys())
    for column in model.columns:
        assert live[column.name]["nullable"] is column.nullable, f"{table_name}.{column.name}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_live_foreign_keys_match_the_model(table_name, connection):
    """Compares target table and ON DELETE rule, which reflection alone does not give."""
    rows = connection.execute(
        text(
            "SELECT k.column_name, k.referenced_table_name, r.delete_rule "
            "FROM information_schema.referential_constraints r "
            "JOIN information_schema.key_column_usage k "
            "  ON k.constraint_name = r.constraint_name "
            " AND k.constraint_schema = r.constraint_schema "
            "WHERE r.constraint_schema = DATABASE() AND r.table_name = :table"
        ),
        {"table": table_name},
    ).fetchall()
    live = sorted((row[0], row[1], row[2]) for row in rows)

    expected = sorted(
        (fk.parent.name, fk.column.table.name, fk.ondelete or "NO ACTION")
        for fk in Base.metadata.tables[table_name].foreign_keys
    )
    assert live == expected


def test_live_unique_constraints_match_the_model(connection):
    rows = connection.execute(
        text(
            "SELECT table_name, constraint_name FROM information_schema.table_constraints "
            "WHERE constraint_schema = DATABASE() AND constraint_type = 'UNIQUE'"
        )
    ).fetchall()
    live = {(row[0], row[1]) for row in rows}

    # MySQL reports both UNIQUE constraints and unique indexes here.
    expected = {
        (table.name, constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    } | {
        (table.name, index.name)
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.unique
    }
    assert live == expected


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_live_indexes_match_the_model(table_name):
    inspector = inspect(engine)
    live = {index["name"] for index in inspector.get_indexes(table_name)}
    expected = {index.name for index in Base.metadata.tables[table_name].indexes}
    assert expected <= live, f"missing indexes: {sorted(expected - live)}"


def test_metadata_and_database_have_no_pending_differences(connection):
    """Alembic's own drift check: an empty diff means nothing is left to migrate."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    context = MigrationContext.configure(connection)
    diff = compare_metadata(context, Base.metadata)
    assert diff == [], f"schema drift detected: {diff}"
