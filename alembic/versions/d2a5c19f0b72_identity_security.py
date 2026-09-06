"""D2 account administration, sessions, audit, and persistent login limits.

Revision ID: d2a5c19f0b72
Revises: ca98ebed8d42
Create Date: 2026-09-05

Existing users are preserved and are not forced to change passwords by migration.
All D1 tokens become invalid under the new signed-token/session contract.
Downgrade deletes session/audit data: never use it as a production recovery shortcut.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "d2a5c19f0b72"
down_revision = "ca98ebed8d42"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.create_check_constraint("ck_users_auth_version", "users", "auth_version >= 0")
    guard = op.create_table("account_guard",
        sa.Column("guard_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.CheckConstraint("guard_id = 1", name="ck_account_guard_singleton"))
    op.bulk_insert(guard, [{"guard_id": 1}])
    op.create_table("auth_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("token_version >= 0", name="ck_auth_sessions_version"))
    op.create_index("ix_auth_sessions_active", "auth_sessions", ["user_id", "revoked_at", "expires_at"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table("audit_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("target_user_id", sa.String(36), sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("actor_role", sa.String(60), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", DATETIME(fsp=6), nullable=False))
    for column in ["actor_id", "target_user_id", "action", "created_at"]:
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])
    op.create_table("login_rate_buckets",
        sa.Column("bucket_key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.BigInteger(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_login_rate_attempts"))
    op.create_index("ix_login_rate_buckets_expires_at", "login_rate_buckets", ["expires_at"])


def downgrade():
    for name in ["login_rate_buckets", "audit_events", "auth_sessions", "account_guard"]:
        op.drop_table(name)
    op.drop_constraint("ck_users_auth_version", "users", type_="check")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "auth_version")
