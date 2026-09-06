"""D3 two-stage admission and private, transactional document storage.

Historical migrations remain unchanged. Legacy paths are NOT trusted for downloads.
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMBLOB

revision = "d3b7a21c8f04"
down_revision = "d2a5c19f0b72"
branch_labels = None
depends_on = None
OLD_HOUSING = ["active", "academic_break", "suspended", "terminated"]
OLD_APPLICATION = [
    "draft",
    "submitted",
    "under_review",
    "pending_documents",
    "accepted",
    "rejected",
]


def upgrade():
    if not context.is_offline_mode():
        duplicate = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT 1 FROM application_documents GROUP BY application_id,document_type HAVING COUNT(*)>1 LIMIT 1"
                )
            )
            .first()
        )
        if duplicate:
            raise RuntimeError(
                "Duplicate legacy document types exist; review them before applying D3. No automatic deletion is performed."
            )
    op.alter_column(
        "students",
        "housing_status",
        existing_type=sa.Enum(*OLD_HOUSING),
        type_=sa.Enum(*OLD_HOUSING, "applicant"),
        existing_nullable=False,
    )
    op.alter_column(
        "applications",
        "status",
        existing_type=sa.Enum(*OLD_APPLICATION),
        type_=sa.Enum(*OLD_APPLICATION, "ready_for_decision"),
        existing_nullable=False,
    )
    op.add_column(
        "students",
        sa.Column(
            "profile_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
    )
    op.create_check_constraint(
        "ck_students_profile_version", "students", "profile_version >= 1"
    )
    op.add_column(
        "applications",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint(
        "ck_applications_version", "applications", "version >= 1"
    )
    for name in ["submitted_at", "review_completed_at"]:
        op.add_column("applications", sa.Column(name, sa.DateTime(), nullable=True))
    op.add_column(
        "applications", sa.Column("prechecked_by", sa.String(36), nullable=True)
    )
    op.create_foreign_key(
        "fk_applications_prechecked_by",
        "applications",
        "users",
        ["prechecked_by"],
        ["user_id"],
        ondelete="SET NULL",
    )
    for name in ["review_notes", "profile_snapshot"]:
        op.add_column("applications", sa.Column(name, sa.Text(), nullable=True))
    op.add_column(
        "applications",
        sa.Column(
            "requested_documents",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.create_unique_constraint(
        "uq_application_document_type",
        "application_documents",
        ["application_id", "document_type"],
    )
    op.add_column(
        "application_documents", sa.Column("content", MEDIUMBLOB(), nullable=True)
    )
    op.add_column(
        "application_documents",
        sa.Column("content_type", sa.String(100), nullable=True),
    )
    op.add_column(
        "application_documents", sa.Column("size_bytes", sa.Integer(), nullable=True)
    )
    op.add_column(
        "application_documents", sa.Column("sha256", sa.String(64), nullable=True)
    )
    op.create_check_constraint(
        "ck_document_size",
        "application_documents",
        "size_bytes IS NULL OR size_bytes > 0",
    )
    op.create_table(
        "application_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(36),
            sa.ForeignKey("applications.application_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_role", sa.String(60), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("from_status", sa.String(40), nullable=True),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("application_version", sa.Integer(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
    )
    op.create_index(
        "ix_application_events_application_id", "application_events", ["application_id"]
    )


def downgrade():
    if context.is_offline_mode():
        raise RuntimeError(
            "D3 offline downgrade is disabled because it cannot verify the data-preservation guards."
        )
    # Fail before destructive DDL if D3-specific data is present. Never silently
    # erase student submissions/files/history just to return to older code.
    if not context.is_offline_mode():
        for query in [
            "SELECT 1 FROM application_events LIMIT 1",
            "SELECT 1 FROM students WHERE profile_version>1 LIMIT 1",
            "SELECT 1 FROM applications WHERE version>1 LIMIT 1",
            "SELECT 1 FROM application_documents WHERE content IS NOT NULL LIMIT 1",
            "SELECT 1 FROM students WHERE housing_status='applicant' LIMIT 1",
            "SELECT 1 FROM applications WHERE status='ready_for_decision' LIMIT 1",
        ]:
            if op.get_bind().execute(sa.text(query)).first():
                raise RuntimeError(
                    "D3 data exists; refusing destructive downgrade. Use a reviewed backup/recovery plan."
                )
    op.drop_table("application_events")
    op.drop_constraint("ck_document_size", "application_documents", type_="check")
    for name in ["sha256", "size_bytes", "content_type", "content"]:
        op.drop_column("application_documents", name)
    op.drop_constraint(
        "uq_application_document_type", "application_documents", type_="unique"
    )
    op.drop_constraint(
        "fk_applications_prechecked_by", "applications", type_="foreignkey"
    )
    for name in [
        "requested_documents",
        "profile_snapshot",
        "review_notes",
        "prechecked_by",
        "review_completed_at",
        "submitted_at",
    ]:
        op.drop_column("applications", name)
    op.drop_constraint("ck_applications_version", "applications", type_="check")
    op.drop_column("applications", "version")
    op.drop_constraint("ck_students_profile_version", "students", type_="check")
    op.drop_column("students", "profile_version")
    op.alter_column(
        "students",
        "housing_status",
        existing_type=sa.Enum(*OLD_HOUSING, "applicant"),
        type_=sa.Enum(*OLD_HOUSING),
        existing_nullable=False,
    )
    op.alter_column(
        "applications",
        "status",
        existing_type=sa.Enum(*OLD_APPLICATION, "ready_for_decision"),
        type_=sa.Enum(*OLD_APPLICATION),
        existing_nullable=False,
    )
