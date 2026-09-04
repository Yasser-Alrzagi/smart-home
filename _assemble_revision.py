"""One-off assembler: rebuilds revision ca98ebed8d42 from the rendered op bodies.

Run from the project root. Deleted after use; it exists only so the 22-table migration
body is machine-generated from Base.metadata rather than transcribed by hand.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HEADER = '''"""initial_schema_all_22_tables

Revision ID: ca98ebed8d42
Revises:
Create Date: 2026-08-30 05:04:47.531487

Initial schema. Extended in place on 2026-08-31 to cover all 22 approved tables:
floors, apartments, services, service_periods, service_registrations and
emergency_reports were added, and rooms.apartment_id / cleaning_cycles.floor_id
became real foreign keys. This revision has never been applied to any database,
so extending it keeps one coherent initial schema instead of stacking a second
revision that would add foreign keys to columns created moments earlier.

The migration body is a faithful render of app.models.Base.metadata. Tables inherit
InnoDB and utf8mb4_unicode_ci from the target database defaults; foreign keys require
InnoDB, so a MyISAM default would silently drop them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca98ebed8d42'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all 22 tables in foreign-key dependency order."""
    '''

MIDDLE = '''


def downgrade() -> None:
    """Drop all 22 tables in reverse dependency order."""
    '''

upgrade_body = (ROOT / "_gen_upgrade.txt").read_text(encoding="utf-8").rstrip("\n")
downgrade_body = (ROOT / "_gen_downgrade.txt").read_text(encoding="utf-8").rstrip("\n")

target = ROOT / "alembic" / "versions" / "ca98ebed8d42_initial_schema_all_22_tables.py"
target.write_text(HEADER + upgrade_body + MIDDLE + downgrade_body + "\n", encoding="utf-8")
print("WROTE", target.name, len(target.read_text(encoding='utf-8').splitlines()), "lines")
