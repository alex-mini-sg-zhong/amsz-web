"""Add Polymarket storage and scheduler tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_000004"
down_revision = "20260519_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_schedule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schedule_key", sa.String(length=128), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_task_id", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("queue_name", sa.String(length=32), nullable=False, server_default="default"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("schedule_key", name="uk_system_schedule_key"),
    )
    op.create_index("idx_system_schedule_due", "system_schedule", ["enabled", "next_run_at"])

    op.create_table(
        "polymarket_sync_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("sync_type", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cursor_in", sa.String(length=255), nullable=True),
        sa.Column("cursor_out", sa.String(length=255), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_polymarket_sync_run_task", "polymarket_sync_run", ["task_id"])

    op.create_table(
        "polymarket_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("resource", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=True),
        sa.Column("active_cursor", sa.String(length=255), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("last_event_updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("source", "resource", "scope", name="uk_polymarket_sync_state_scope"),
    )

    op.create_table(
        "polymarket_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("polymarket_event_id", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("subcategory", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=True),
        sa.Column("restricted", sa.Boolean(), nullable=True),
        sa.Column("enable_order_book", sa.Boolean(), nullable=True),
        sa.Column("neg_risk", sa.Boolean(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("open_interest", sa.Float(), nullable=True),
        sa.Column("volume_24hr", sa.Float(), nullable=True),
        sa.Column("volume_1wk", sa.Float(), nullable=True),
        sa.Column("volume_1mo", sa.Float(), nullable=True),
        sa.Column("volume_1yr", sa.Float(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("source_created_at", sa.DateTime(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("polymarket_event_id", name="uk_polymarket_event_id"),
    )
    op.create_index("idx_polymarket_event_slug", "polymarket_event", ["slug"])
    op.create_index("idx_polymarket_event_active_closed", "polymarket_event", ["active", "closed"])
    op.create_index("idx_polymarket_event_featured_volume", "polymarket_event", ["featured", "volume"])

    op.create_table(
        "polymarket_event_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("polymarket_event_id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_time", sa.DateTime(), nullable=False),
        sa.Column("snapshot_granularity", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("open_interest", sa.Float(), nullable=True),
        sa.Column("volume_24hr", sa.Float(), nullable=True),
        sa.Column("volume_1wk", sa.Float(), nullable=True),
        sa.Column("volume_1mo", sa.Float(), nullable=True),
        sa.Column("volume_1yr", sa.Float(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("polymarket_event_id", "snapshot_time", "snapshot_granularity", name="uk_polymarket_event_snapshot_bucket"),
    )
    op.create_index("idx_polymarket_event_snapshot_event_time", "polymarket_event_snapshot", ["polymarket_event_id", "snapshot_time"])
    op.create_index("idx_polymarket_event_snapshot_time", "polymarket_event_snapshot", ["snapshot_time"])

    op.create_table(
        "polymarket_event_raw",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("polymarket_event_id", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("polymarket_event_id", "payload_hash", name="uk_polymarket_event_raw_hash"),
    )
    op.create_index("idx_polymarket_event_raw_event", "polymarket_event_raw", ["polymarket_event_id"])


def downgrade() -> None:
    op.drop_index("idx_polymarket_event_raw_event", table_name="polymarket_event_raw")
    op.drop_table("polymarket_event_raw")
    op.drop_index("idx_polymarket_event_snapshot_time", table_name="polymarket_event_snapshot")
    op.drop_index("idx_polymarket_event_snapshot_event_time", table_name="polymarket_event_snapshot")
    op.drop_table("polymarket_event_snapshot")
    op.drop_index("idx_polymarket_event_featured_volume", table_name="polymarket_event")
    op.drop_index("idx_polymarket_event_active_closed", table_name="polymarket_event")
    op.drop_index("idx_polymarket_event_slug", table_name="polymarket_event")
    op.drop_table("polymarket_event")
    op.drop_table("polymarket_sync_state")
    op.drop_index("idx_polymarket_sync_run_task", table_name="polymarket_sync_run")
    op.drop_table("polymarket_sync_run")
    op.drop_index("idx_system_schedule_due", table_name="system_schedule")
    op.drop_table("system_schedule")
