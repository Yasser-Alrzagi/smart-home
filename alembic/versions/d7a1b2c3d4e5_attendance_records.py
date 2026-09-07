"""D7 daily attendance ledger: one row per student per date.

Revision ID: d7a1b2c3d4e5
Revises: d3b7a21c8f04
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "d7a1b2c3d4e5"
down_revision = "d3b7a21c8f04"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attendance_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Enum("present", "late", "absent", "excused", name="attendancestatus"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(36), nullable=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="officer"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.student_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint("student_id", "record_date", name="uq_attendance_student_date"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_attendance_records_student_id", "attendance_records", ["student_id"])
    op.create_index("ix_attendance_records_record_date", "attendance_records", ["record_date"])


def downgrade():
    op.drop_table("attendance_records")
