"""Validates that revision ca98ebed8d42 is an exact replay of the ORM metadata.

The migration is loaded by explicit path and its ``op`` calls are replayed into a fresh
MetaData, which is then compared field by field against ``app.models.INITIAL_METADATA``.
This catches the failure mode Alembic itself never reports: a migration that runs
cleanly but produces a schema the models do not expect. Nothing here touches MySQL.
"""

import pytest
from sqlalchemy import Index, MetaData, Table, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.config import BASE_DIR
import json

INITIAL = json.loads((BASE_DIR / "tests/fixtures/initial_schema.json").read_text())

REVISION_ID = "ca98ebed8d42"
REVISION_PATH = (
    BASE_DIR / "alembic" / "versions" / f"{REVISION_ID}_initial_schema_all_22_tables.py"
)
DIALECT = mysql.dialect()


class _OpRecorder:
    """Stands in for ``alembic.op`` and rebuilds the schema the migration describes."""

    def __init__(self):
        self.metadata = MetaData()
        self.created_tables = []
        self.created_indexes = []
        self.dropped_tables = []
        self.dropped_indexes = []
        self.events = []  # ordered (action, table, name) log, needed to check interleaving

    def f(self, name):
        return name

    def create_table(self, name, *args, **kwargs):
        self.created_tables.append(name)
        self.events.append(("create_table", name, name))
        return Table(name, self.metadata, *args, **kwargs)

    def create_index(self, name, table_name, columns, unique=False, **kwargs):
        table = self.metadata.tables[table_name]
        Index(name, *[table.c[column] for column in columns], unique=unique)
        self.created_indexes.append(name)
        self.events.append(("create_index", table_name, name))

    def drop_table(self, name, **kwargs):
        self.dropped_tables.append(name)
        self.events.append(("drop_table", name, name))

    def drop_index(self, name, table_name=None, **kwargs):
        self.dropped_indexes.append((name, table_name))
        self.events.append(("drop_index", table_name, name))


def _load_revision():
    """Execute the revision file in an isolated namespace, without Alembic's registry.

    Loading by path deliberately bypasses ScriptDirectory so this test still reports the
    schema truth even while more than one file claims the same revision id.
    """
    namespace = {"__name__": f"revision_{REVISION_ID}", "__file__": str(REVISION_PATH)}
    source = REVISION_PATH.read_text(encoding="utf-8")
    exec(compile(source, str(REVISION_PATH), "exec"), namespace)  # noqa: S102
    return namespace


def _replay(direction):
    namespace = _load_revision()
    recorder = _OpRecorder()
    namespace["op"] = recorder
    namespace[direction]()
    return recorder


def _fingerprint(table):
    """Everything about a table that the database will actually enforce."""
    return {
        "columns": [
            (column.name, column.type.compile(DIALECT), column.nullable)
            for column in table.columns
        ],
        "primary_key": [column.name for column in table.primary_key.columns],
        "foreign_keys": sorted(
            (fk.parent.name, fk.target_fullname, fk.ondelete or "NO ACTION")
            for fk in table.foreign_keys
        ),
        "unique_constraints": sorted(
            (constraint.name, tuple(sorted(c.name for c in constraint.columns)))
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ),
        "indexes": sorted(
            (index.name, tuple(c.name for c in index.columns), bool(index.unique))
            for index in table.indexes
        ),
    }


# Frozen initial contract; new migrations are checked end-to-end against current models.
INITIAL_METADATA = _replay("upgrade").metadata


@pytest.fixture(scope="module")
def upgraded():
    return _replay("upgrade")


@pytest.fixture(scope="module")
def downgraded():
    return _replay("downgrade")


def test_revision_identifiers():
    namespace = _load_revision()
    assert namespace["revision"] == REVISION_ID
    assert namespace["down_revision"] is None, "this must remain the initial revision"
    assert namespace["branch_labels"] is None
    assert namespace["depends_on"] is None


def test_exactly_one_file_declares_this_revision():
    """Two files with the same id make `alembic upgrade` pick one non-deterministically."""
    versions = REVISION_PATH.parent
    claiming = [
        path
        for path in versions.glob("*.py")
        if f"revision: str = '{REVISION_ID}'" in path.read_text(encoding="utf-8")
    ]
    assert [path.name for path in claiming] == [REVISION_PATH.name]


def test_upgrade_creates_all_22_tables(upgraded):
    assert len(upgraded.created_tables) == 22
    assert len(set(upgraded.created_tables)) == 22
    assert set(upgraded.metadata.tables) == set(INITIAL)


@pytest.mark.parametrize("table_name", sorted(INITIAL_METADATA.tables))
def test_table_matches_the_model(upgraded, table_name):
    assert json.loads(json.dumps(_fingerprint(upgraded.metadata.tables[table_name]))) == INITIAL[table_name]


def test_upgrade_creates_parents_before_children(upgraded):
    already_created = set()
    for name in upgraded.created_tables:
        table = upgraded.metadata.tables[name]
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            assert parent == name or parent in already_created, (
                f"{name} references {parent} before it exists"
            )
        already_created.add(name)


def test_downgrade_drops_every_table_once(downgraded):
    assert len(downgraded.dropped_tables) == 22
    assert set(downgraded.dropped_tables) == set(INITIAL_METADATA.tables)


def test_downgrade_never_drops_a_table_that_is_still_referenced(downgraded):
    """A table may only be dropped once nothing that remains points at it."""
    remaining = set(INITIAL_METADATA.tables)
    for name in downgraded.dropped_tables:
        remaining.discard(name)
        blockers = [
            other
            for other in remaining
            for fk in INITIAL_METADATA.tables[other].foreign_keys
            if fk.column.table.name == name
        ]
        assert not blockers, f"dropping {name} still leaves referencing tables {blockers}"


def test_downgrade_drops_indexes_before_their_table(downgraded):
    """Dropping an index after its table would raise; the ordered log proves it doesn't."""
    gone = set()
    for action, table_name, _ in downgraded.events:
        assert table_name not in gone, f"{action} on {table_name} after it was dropped"
        if action == "drop_table":
            gone.add(table_name)


def test_every_index_in_the_models_is_created_and_dropped(upgraded, downgraded):
    model_indexes = {
        index.name for table in INITIAL_METADATA.tables.values() for index in table.indexes
    }
    assert set(upgraded.created_indexes) == model_indexes
    # DROP TABLE implicitly removes indexes. Explicit DROP INDEX before an FK's
    # table is invalid on InnoDB; the live cycle regression covers real DDL.
    removed_with_tables = {
        index.name
        for name in downgraded.dropped_tables
        for index in INITIAL_METADATA.tables[name].indexes
    }
    assert removed_with_tables == model_indexes
    assert downgraded.dropped_indexes == []


def test_no_invented_schema_elements(upgraded):
    """Nothing in the migration may exist that the approved models do not declare."""
    extra_tables = set(upgraded.metadata.tables) - set(INITIAL_METADATA.tables)
    assert not extra_tables
    for name, table in upgraded.metadata.tables.items():
        model_columns = set(INITIAL_METADATA.tables[name].columns.keys())
        assert not set(table.columns.keys()) - model_columns, name


def test_migration_ddl_compiles_for_mysql(upgraded):
    from sqlalchemy.schema import CreateTable

    for table in upgraded.metadata.sorted_tables:
        assert table.name in str(CreateTable(table).compile(dialect=DIALECT))
