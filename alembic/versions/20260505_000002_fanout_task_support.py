"""Add fanout task support."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260505_000002"
down_revision = "20260430_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("task", "status", type_=sa.String(length=32), existing_type=sa.String(length=16))
    op.alter_column(
        "task_event",
        "from_status",
        type_=sa.String(length=32),
        existing_type=sa.String(length=16),
    )
    op.alter_column(
        "task_event",
        "to_status",
        type_=sa.String(length=32),
        existing_type=sa.String(length=16),
    )
    op.add_column(
        "task",
        sa.Column(
            "task_role",
            sa.String(length=16),
            nullable=False,
            server_default="standalone",
        ),
    )
    op.add_column("task", sa.Column("parent_task_id", sa.Integer(), nullable=True))
    op.add_column("task", sa.Column("shard_index", sa.Integer(), nullable=True))
    op.add_column("task", sa.Column("shard_key", sa.String(length=128), nullable=True))
    op.add_column(
        "task",
        sa.Column("total_children", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "task",
        sa.Column("succeeded_children", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "task",
        sa.Column("failed_children", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "task",
        sa.Column("running_children", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("task", sa.Column("child_summary", sa.JSON(), nullable=True))
    op.add_column(
        "task",
        sa.Column(
            "aggregation_dispatched",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "idx_task_parent_dispatch",
        "task",
        ["parent_task_id", "status", "scheduled_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_task_parent_dispatch", table_name="task")
    op.drop_column("task", "aggregation_dispatched")
    op.drop_column("task", "child_summary")
    op.drop_column("task", "running_children")
    op.drop_column("task", "failed_children")
    op.drop_column("task", "succeeded_children")
    op.drop_column("task", "total_children")
    op.drop_column("task", "shard_key")
    op.drop_column("task", "shard_index")
    op.drop_column("task", "parent_task_id")
    op.drop_column("task", "task_role")
    op.alter_column("task_event", "to_status", type_=sa.String(length=16), existing_type=sa.String(length=32))
    op.alter_column(
        "task_event",
        "from_status",
        type_=sa.String(length=16),
        existing_type=sa.String(length=32),
    )
    op.alter_column("task", "status", type_=sa.String(length=16), existing_type=sa.String(length=32))
