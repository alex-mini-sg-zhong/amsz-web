"""Backfill runtime_config_revision.config_json with all current fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260612_000006"
down_revision = "20260604_000005"
branch_labels = None
depends_on = None

FULL_DEFAULTS: dict[str, object] = {
    "app_name": "amsz-task-service",
    "app_env": "${APP_ENV}",
    "log_level": "INFO",
    "log_dir": "data",
    "log_file_name": "amsz-task-service.log",
    "log_file_max_bytes": 52428800,
    "log_file_backup_count": 5,
    "api_host": "0.0.0.0",
    "api_port": 8200,
    "api_key": "${API_KEY}",
    "worker_id": "${WORKER_ID}",
    "pod_name": "${POD_NAME}",
    "worker_queue": "${WORKER_QUEUE}",
    "worker_profile": "default",
    "worker_concurrency": "${WORKER_CONCURRENCY}",
    "worker_poll_interval_seconds": 2.0,
    "worker_claim_batch_size": 5,
    "worker_lease_seconds": 30,
    "worker_heartbeat_interval_seconds": 10,
    "worker_recover_limit": 100,
    "task_fanout_shard_size": 2,
    "task_fanout_max_children": 10,
    "scheduler_enabled": True,
    "scheduler_tick_interval_seconds": 10.0,
    "scheduler_max_due_schedules": 10,
    "polymarket_base_url": "https://gamma-api.polymarket.com",
    "polymarket_request_timeout_seconds": 10.0,
    "polymarket_catalog_limit": 200,
    "polymarket_snapshot_limit": 100,
    "szdm_queue_name": "default",
    "szdm_subtask_max_attempts": 3,
    "szdm_subtask_timeout_seconds": 7200,
    "szdm_scheduler_max_jobs": 10,
    "szdm_scheduler_per_job_dispatch_limit": 50,
    "szdm_default_max_parallel_children": 100,
    "szdm_default_dispatch_batch_size": 50,
    "szdm_default_reuse_window_seconds": 86400,
    "szdm_s3_bucket": "amszbucket",
    "szdm_s3_root_dir": "amsz",
    "szdm_s3_provider": "hws3",
    "szdm_s3_region": "us-east-1",
    "szdm_s3_endpoint_url": "http://localhost:9000",
    "task_event_db_enabled": True,
    "task_attempt_cleanup_on_completion": False,
}


def upgrade() -> None:
    connection = op.get_bind()
    table = sa.table(
        "runtime_config_revision",
        sa.column("id", sa.Integer()),
        sa.column("config_json", sa.JSON()),
    )

    rows = connection.execute(sa.select(table.c.id, table.c.config_json))
    for row_id, existing_json in rows:
        existing: dict[str, object] = existing_json if isinstance(existing_json, dict) else {}
        merged = {**FULL_DEFAULTS, **existing}
        connection.execute(
            table.update().where(table.c.id == row_id).values(config_json=merged)
        )


def downgrade() -> None:
    """No downgrade — config backfill is additive and safe to keep."""
    pass
