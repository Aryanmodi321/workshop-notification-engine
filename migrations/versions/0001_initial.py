"""Initial workshop, registration, and transactional outbox schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workshops",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.CheckConstraint("status in ('active', 'cancelled')", name="ck_workshop_status"),
    )
    op.create_table(
        "registrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workshop_id",
            sa.Integer(),
            sa.ForeignKey("workshops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_id", sa.String(200), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="registered"),
        sa.UniqueConstraint("workshop_id", "member_id", name="uq_registration_workshop_member"),
        sa.CheckConstraint("status in ('registered', 'cancelled')", name="ck_registration_status"),
    )
    op.create_index("ix_registrations_workshop_id", "registrations", ["workshop_id"])
    op.create_table(
        "notification_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("recipient", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(36), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'processing', 'sent', 'dead')", name="ck_notification_job_status"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_notification_job_attempts"),
    )
    op.create_index(
        "ix_notification_jobs_ready",
        "notification_jobs",
        ["status", "next_attempt_at", "created_at"],
    )
    op.create_index("ix_notification_jobs_locked_at", "notification_jobs", ["status", "locked_at"])
    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("notification_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_notification_attempts_job_id", "notification_attempts", ["job_id", "attempt_number"]
    )


def downgrade() -> None:
    op.drop_table("notification_attempts")
    op.drop_index("ix_notification_jobs_locked_at", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_ready", table_name="notification_jobs")
    op.drop_table("notification_jobs")
    op.drop_index("ix_registrations_workshop_id", table_name="registrations")
    op.drop_table("registrations")
    op.drop_table("workshops")
