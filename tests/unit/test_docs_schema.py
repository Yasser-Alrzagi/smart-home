"""Keeps docs/database.md and the ORM models from drifting apart.

The specification requires the database, the API and the documentation to stay
consistent, so the document is parsed and compared against the mapped metadata rather
than trusted. Section 4 of the document is the authority for columns; section 5 for
enumeration value sets.
"""
import re

import pytest
from sqlalchemy.dialects import mysql

from app.core.config import BASE_DIR
from app.models import Base

DOC_PATH = BASE_DIR / "docs" / "database.md"
DIALECT = mysql.dialect()

_HEADING = re.compile(r"^#### `([a-z_]+)`")
_FK_NOTE = re.compile(r"FK `([a-z_]+)` (CASCADE|SET NULL|RESTRICT)")


def _parse_column_tables():
    """{table_name: [(column, type, null, notes), ...]} from section 4."""
    text = DOC_PATH.read_text(encoding="utf-8")
    section = text.split("## 4. Table Definitions")[1].split("## 5.")[0]

    tables = {}
    current = None
    for line in section.splitlines():
        heading = _HEADING.match(line)
        if heading:
            current = heading.group(1)
            tables[current] = []
            continue
        if current and line.startswith("| `"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            tables[current].append(
                (cells[0].strip("`"), cells[1], cells[2], cells[4] if len(cells) > 4 else "")
            )
    return tables


DOC_TABLES = _parse_column_tables()


def test_document_covers_exactly_the_mapped_tables():
    assert set(DOC_TABLES) == set(Base.metadata.tables)


@pytest.mark.parametrize("table_name", sorted(DOC_TABLES))
def test_documented_columns_match_the_model(table_name):
    table = Base.metadata.tables[table_name]
    documented = [entry[0] for entry in DOC_TABLES[table_name]]
    assert documented == [column.name for column in table.columns]


@pytest.mark.parametrize("table_name", sorted(DOC_TABLES))
def test_documented_nullability_and_types_match(table_name):
    table = Base.metadata.tables[table_name]
    for column_name, doc_type, doc_null, _ in DOC_TABLES[table_name]:
        column = table.c[column_name]
        assert column.nullable is (doc_null.upper() == "YES"), f"{table_name}.{column_name}"

        rendered = column.type.compile(DIALECT).upper()
        expected = doc_type.upper().replace("BOOLEAN", "BOOL")
        if expected.startswith("ENUM"):
            assert rendered.startswith("ENUM"), f"{table_name}.{column_name}"
        else:
            assert rendered == expected, f"{table_name}.{column_name}"


@pytest.mark.parametrize("table_name", sorted(DOC_TABLES))
def test_documented_foreign_keys_match(table_name):
    table = Base.metadata.tables[table_name]
    for column_name, _, _, notes in DOC_TABLES[table_name]:
        column = table.c[column_name]
        note = _FK_NOTE.search(notes)
        actual = [
            (fk.column.table.name, fk.ondelete or "") for fk in column.foreign_keys
        ]
        if note is None:
            assert not actual, f"{table_name}.{column_name} has an undocumented FK {actual}"
        else:
            assert actual == [note.groups()], f"{table_name}.{column_name}"


def test_documented_enum_value_sets_match_the_python_enums():
    """Compare actual ordered values, not just type names (foundation regression)."""
    text = DOC_PATH.read_text(encoding="utf-8")
    section = text.split("## 5. Enumeration Value Sets")[1].split("## 6.")[0]
    documented = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        name = cells[0].strip("`").replace("_", "")
        assert name not in documented, f"duplicate documented enum: {name}"
        documented[name] = [value.strip() for value in cells[1].split(",")]
    stored = {
        column.type.name: list(column.type.enums)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if getattr(column.type, "enums", None)
    }
    assert documented == stored
