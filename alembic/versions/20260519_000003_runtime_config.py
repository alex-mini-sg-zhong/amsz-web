"""Add runtime config revision tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260519_000003"
down_revision = "20260505_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_config_revision",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_revision_id", sa.Integer(), nullable=True),
        sa.Column("change_note", sa.String(length=255), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("published_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "version_no",
            name="uk_runtime_config_revision_version",
        ),
    )
    op.create_index(
        "ix_runtime_config_revision_status",
        "runtime_config_revision",
        ["status"],
    )

    op.create_table(
        "runtime_config_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("active_revision_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["active_revision_id"],
            ["runtime_config_revision.id"],
            name="fk_runtime_config_state_active_revision",
        ),
    )

    default_config = {
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
        "worker_concurrency": "${WORKER_CONCURRENCY}",
        "worker_poll_interval_seconds": 2.0,
        "worker_claim_batch_size": 5,
        "worker_lease_seconds": 30,
        "worker_heartbeat_interval_seconds": 10,
        "worker_recover_limit": 100,
        "task_fanout_shard_size": 2,
        "task_fanout_max_children": 10,
    }
    op.execute(
        sa.table(
            "runtime_config_revision",
            sa.column("id", sa.Integer()),
            sa.column("version_no", sa.Integer()),
            sa.column("status", sa.String()),
            sa.column("schema_version", sa.Integer()),
            sa.column("base_revision_id", sa.Integer()),
            sa.column("change_note", sa.String()),
            sa.column("config_json", sa.JSON()),
            sa.column("created_by", sa.String()),
            sa.column("published_by", sa.String()),
            sa.column("published_at", sa.DateTime()),
        ).insert().values(
            id=1,
            version_no=1,
            status="ACTIVE",
            schema_version=1,
            base_revision_id=None,
            change_note="Initial runtime configuration",
            config_json=default_config,
            created_by="migration",
            published_by="migration",
            published_at=sa.text("CURRENT_TIMESTAMP"),
        )
    )
    op.execute(
        sa.table(
            "runtime_config_state",
            sa.column("id", sa.Integer()),
            sa.column("active_revision_id", sa.Integer()),
        ).insert().values(id=1, active_revision_id=1)
    )


def downgrade() -> None:
    op.drop_table("runtime_config_state")
    op.drop_index("ix_runtime_config_revision_status", table_name="runtime_config_revision")
    op.drop_table("runtime_config_revision")
