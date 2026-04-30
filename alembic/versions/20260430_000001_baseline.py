"""Baseline schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260430_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("queue_name", sa.String(length=32), nullable=False),
        sa.Column("biz_key", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "scheduled_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "task_type",
            "idempotency_key",
            name="uk_task_idempotency",
        ),
    )
    op.create_index(
        "idx_task_dispatch",
        "task",
        ["queue_name", "status", "scheduled_at", "priority", "id"],
    )
    op.create_index("idx_task_lease", "task", ["status", "lease_until"])
    op.create_index("idx_task_biz", "task", ["task_type", "biz_key"])
    op.create_index("idx_task_created", "task", ["created_at"])

    op.create_table(
        "task_attempt",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("pod_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name="fk_attempt_task"),
        sa.UniqueConstraint("task_id", "attempt_no", name="uk_task_attempt"),
    )
    op.create_index("idx_attempt_task", "task_attempt", ["task_id"])

    op.create_table(
        "task_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], name="fk_event_task"),
    )
    op.create_index("idx_event_task", "task_event", ["task_id"])


def downgrade() -> None:
    op.drop_index("idx_event_task", table_name="task_event")
    op.drop_table("task_event")
    op.drop_index("idx_attempt_task", table_name="task_attempt")
    op.drop_table("task_attempt")
    op.drop_index("idx_task_created", table_name="task")
    op.drop_index("idx_task_biz", table_name="task")
    op.drop_index("idx_task_lease", table_name="task")
    op.drop_index("idx_task_dispatch", table_name="task")
    op.drop_table("task")
