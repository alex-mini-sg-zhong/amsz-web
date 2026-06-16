"""Create alembic_schema table for version management."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260616_000007"
down_revision = "20260612_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The bootstrap runner may have already created this table via raw SQL.
    # Use op.create_table (dialect-agnostic auto-increment) wrapped in a
    # try/except for idempotency.
    try:
        op.create_table(
            "alembic_schema",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("version_num", sa.String(length=32), nullable=False),
            sa.Column("direction", sa.String(length=8), nullable=False),
            sa.Column("migration_source", sa.Text(), nullable=True),
            sa.Column(
                "applied_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    except Exception:
        # table already exists (created by bootstrap runner)
        pass

    # Create index (idempotent on MySQL; SQLite errors are harmless)
    try:
        op.create_index(
            "idx_alembic_schema_applied",
            "alembic_schema",
            ["applied_at"],
        )
    except Exception:
        pass

    # Backfill: migrate existing alembic_version data into alembic_schema
    connection = op.get_bind()
    try:
        existing = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).fetchone()
        if existing is not None:
            already = connection.execute(
                sa.text(
                    "SELECT 1 FROM alembic_schema "
                    "WHERE version_num = :ver AND direction = 'upgrade'"
                ),
                {"ver": existing[0]},
            ).fetchone()
            if already is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO alembic_schema (version_num, direction) "
                        "VALUES (:version, 'upgrade')"
                    ),
                    {"version": existing[0]},
                )
    except Exception:
        # alembic_version may not exist (fresh install)
        pass


def downgrade() -> None:
    op.drop_index("idx_alembic_schema_applied", table_name="alembic_schema")
    op.drop_table("alembic_schema")
