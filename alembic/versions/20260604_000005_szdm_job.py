"""Add SZDM job and item tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260604_000005"
down_revision = "20260525_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "szdm_job",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parent_task_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("job_s3_prefix", sa.String(length=512), nullable=False),
        sa.Column("input_s3_key", sa.String(length=512), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dispatched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("running_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_parallel_children", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("dispatch_batch_size", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("reuse_window_seconds", sa.Integer(), nullable=False, server_default="86400"),
        sa.Column("report_status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("report_s3_key", sa.String(length=512), nullable=True),
        sa.Column("report_hash", sa.String(length=64), nullable=True),
        sa.Column("report_summary_json", sa.JSON(), nullable=True),
        sa.Column("report_metric_summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("parent_task_id", name="uk_szdm_job_parent_task"),
    )
    op.create_index("idx_szdm_job_status_priority", "szdm_job", ["status", "priority", "updated_at"])
    op.create_index("idx_szdm_job_report_status", "szdm_job", ["report_status", "updated_at"])

    op.create_table(
        "szdm_item",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=255), nullable=False),
        sa.Column("condition_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("reuse_status", sa.String(length=32), nullable=False, server_default="NOT_CHECKED"),
        sa.Column("child_task_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_s3_key", sa.String(length=512), nullable=True),
        sa.Column("result_timestamp", sa.DateTime(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("display_summary_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("job_id", "item_key", "condition_key", name="uk_szdm_item_key_condition"),
    )
    op.create_index("idx_szdm_item_job_status_priority", "szdm_item", ["job_id", "status", "priority", "item_index"])
    op.create_index("idx_szdm_item_child_task", "szdm_item", ["job_id", "child_task_id"])
    op.create_index("idx_szdm_item_key", "szdm_item", ["job_id", "item_key"])
    op.create_index("idx_szdm_item_condition", "szdm_item", ["job_id", "condition_key"])


def downgrade() -> None:
    op.drop_index("idx_szdm_item_condition", table_name="szdm_item")
    op.drop_index("idx_szdm_item_key", table_name="szdm_item")
    op.drop_index("idx_szdm_item_child_task", table_name="szdm_item")
    op.drop_index("idx_szdm_item_job_status_priority", table_name="szdm_item")
    op.drop_table("szdm_item")
    op.drop_index("idx_szdm_job_report_status", table_name="szdm_job")
    op.drop_index("idx_szdm_job_status_priority", table_name="szdm_job")
    op.drop_table("szdm_job")
