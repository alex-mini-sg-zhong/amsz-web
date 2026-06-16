from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.bootstrap.logging import configure_bootstrap_logging
from app.bootstrap.runtime import load_bootstrap_settings
from app.core.app_logging import get_logger
from app.core.config import DEFAULT_LOG_LEVEL


class SchemaMigrationRunner:
    def __init__(
        self,
        *,
        database_url: str,
        lock_name: str = "amsz_schema_migration",
        lock_timeout_seconds: int = 60,
    ) -> None:
        self.database_url = database_url
        self.lock_name = lock_name
        self.lock_timeout_seconds = lock_timeout_seconds
        self.logger = get_logger("app.bootstrap.migration")

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.logger.info("Starting schema version check")
        engine = self._create_engine()
        try:
            with engine.connect() as connection:
                lock_acquired = False
                if self._uses_mysql():
                    lock_acquired = self._acquire_named_lock(connection)
                try:
                    self._ensure_alembic_schema_table(connection)
                    local_head = self._get_local_head()
                    db_revision = self._get_db_revision(connection)

                    if db_revision is None:
                        self.logger.info("Fresh database – running full upgrade")
                        self._store_migration_sources(
                            connection, self._get_script(), None, local_head
                        )
                        self._run_alembic_command(connection, "upgrade", "head")
                    elif db_revision == local_head:
                        self.logger.info(
                            "Schema is up-to-date db_revision=%s", db_revision
                        )
                        # Backfill: store sources for any revisions that lack them
                        self._store_migration_sources(
                            connection, self._get_script(), None, local_head
                        )
                    else:
                        self._migrate_to_target(connection, db_revision, local_head)

                    self.logger.info("Schema version check completed")
                finally:
                    if lock_acquired:
                        self._release_named_lock(connection)
                    connection.commit()
        finally:
            engine.dispose()

    # ------------------------------------------------------------------
    # migration logic
    # ------------------------------------------------------------------

    def _migrate_to_target(
        self, connection: Connection, db_revision: str, target: str
    ) -> None:
        script = self._get_script()
        chain = self._revision_chain(script)

        if db_revision not in chain:
            self.logger.error(
                "Unknown db revision %s – not in local revision chain", db_revision
            )
            raise SystemExit(1)

        db_index = chain.index(db_revision)
        target_index = chain.index(target)

        if db_index < target_index:
            self.logger.info(
                "Database behind – upgrading %s -> %s", db_revision, target
            )
            # Store migration sources BEFORE running upgrade
            self._store_migration_sources(connection, script, db_revision, target)
            self._run_alembic_command(connection, "upgrade", target)
        elif db_index > target_index:
            self.logger.info(
                "Database ahead – downgrading %s -> %s", db_revision, target
            )
            # Downgrade revisions from db_revision down to (but not including) target
            self._downgrade_to_target(connection, script, chain, db_revision, target)
        else:
            self.logger.info("Schema is up-to-date (post-check)")

    def _downgrade_to_target(
        self,
        connection: Connection,
        script,
        chain: list[str],
        db_revision: str,
        target: str,
    ) -> None:
        """Execute downgrades in reverse order, using stored sources if needed."""
        db_index = chain.index(db_revision)
        target_index = chain.index(target)
        # Revisions to downgrade: from db_index down to target_index + 1
        to_downgrade = list(reversed(chain[target_index + 1 : db_index + 1]))

        for revision in to_downgrade:
            self.logger.info("Downgrading revision %s", revision)
            rev_obj = script.get_revision(revision)
            if rev_obj is not None and rev_obj.path and os.path.exists(rev_obj.path):
                # Local file exists — use Alembic directly
                self._run_alembic_command(connection, "downgrade", revision)
            else:
                # Rollback scenario — load source from alembic_schema
                self._downgrade_from_stored_source(connection, revision)

    def _downgrade_from_stored_source(
        self, connection: Connection, revision: str
    ) -> None:
        """Load migration source from alembic_schema and execute downgrade."""
        row = connection.execute(
            text(
                "SELECT migration_source FROM alembic_schema "
                "WHERE version_num = :rev AND direction = 'upgrade' "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"rev": revision},
        ).fetchone()

        if row is None or row[0] is None:
            self.logger.error(
                "No stored migration source found for revision %s — "
                "cannot downgrade",
                revision,
            )
            raise SystemExit(1)

        source: str = row[0]

        # Write the source to a temporary migration file so Alembic can use it
        versions_dir = self._alembic_ini_path().parent / "versions"
        tmp_path = versions_dir / f"{revision}_rollback.py"
        try:
            tmp_path.write_text(source, encoding="utf-8")
            # Clear Alembic's script cache so it picks up the new file
            script = self._get_script()
            script._catch_up_to_present = None
            script.revision_map  # force reload
            self._run_alembic_command(connection, "downgrade", revision)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # ------------------------------------------------------------------
    # source storage
    # ------------------------------------------------------------------

    def _store_migration_sources(
        self,
        connection: Connection,
        script,
        db_revision: str | None,
        target: str,
    ) -> None:
        """Store migration file sources in alembic_schema before/after upgrading."""
        chain = self._revision_chain(script)
        if db_revision is None:
            start_index = 0
        else:
            start_index = chain.index(db_revision) + 1
        end_index = chain.index(target) + 1

        stored = 0
        for revision in chain[start_index:end_index]:
            rev_obj = script.get_revision(revision)
            source: str | None = None

            if rev_obj is not None and rev_obj.path and os.path.exists(rev_obj.path):
                source = Path(rev_obj.path).read_text(encoding="utf-8")
            else:
                # Fallback: try to find the file by naming convention
                versions_dir = self._alembic_ini_path().parent / "versions"
                for candidate in versions_dir.glob(f"{revision}_*.py"):
                    source = candidate.read_text(encoding="utf-8")
                    break

            if source is None:
                self.logger.warning(
                    "Migration source not found for %s", revision
                )
                continue

            existing = connection.execute(
                text(
                    "SELECT 1 FROM alembic_schema "
                    "WHERE version_num = :rev AND direction = 'upgrade'"
                ),
                {"rev": revision},
            ).fetchone()
            if existing is not None:
                connection.execute(
                    text(
                        "UPDATE alembic_schema SET migration_source = :src "
                        "WHERE version_num = :rev AND direction = 'upgrade'"
                    ),
                    {"src": source, "rev": revision},
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO alembic_schema "
                        "(version_num, direction, migration_source) "
                        "VALUES (:rev, 'upgrade', :src)"
                    ),
                    {"rev": revision, "src": source},
                )
            stored += 1

        if stored:
            self.logger.info("Stored %d migration sources in alembic_schema", stored)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _ensure_alembic_schema_table(self, connection: Connection) -> None:
        """Create alembic_schema if it does not exist (idempotent)."""
        if self._uses_mysql():
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_schema ("
                    "  id INTEGER PRIMARY KEY AUTO_INCREMENT,"
                    "  version_num VARCHAR(32) NOT NULL,"
                    "  direction VARCHAR(8) NOT NULL,"
                    "  migration_source TEXT,"
                    "  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_alembic_schema_applied "
                    "ON alembic_schema (applied_at)"
                )
            )
        else:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_schema ("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  version_num VARCHAR(32) NOT NULL,"
                    "  direction VARCHAR(8) NOT NULL,"
                    "  migration_source TEXT,"
                    "  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            try:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_alembic_schema_applied "
                        "ON alembic_schema (applied_at)"
                    )
                )
            except Exception:
                pass

        # Ensure migration_source column exists (for DBs created before this change)
        try:
            connection.execute(
                text(
                    "ALTER TABLE alembic_schema "
                    "ADD COLUMN migration_source TEXT"
                )
            )
        except Exception:
            pass

    def _get_db_revision(self, connection: Connection) -> str | None:
        rows = connection.execute(
            text(
                "SELECT version_num, direction FROM alembic_schema ORDER BY id ASC"
            )
        ).fetchall()

        if rows:
            applied: set[str] = set()
            for version_num, direction in rows:
                if direction == "upgrade":
                    applied.add(version_num)
                else:  # downgrade
                    applied.discard(version_num)
            if applied:
                return max(applied)

        # fallback: check legacy alembic_version table
        row = self._get_legacy_alembic_version(connection)
        return row[0] if row is not None else None

    def _get_legacy_alembic_version(self, connection: Connection):
        try:
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
        except Exception:
            return None

    def _get_local_head(self) -> str:
        script = self._get_script()
        head = script.get_current_head()
        if head is None:
            raise RuntimeError("No migration head found in alembic script directory")
        return head

    @staticmethod
    def _revision_chain(script) -> list[str]:
        revisions: list[str] = []
        current = script.get_revision("head")
        while current is not None:
            revisions.append(current.revision)
            if current.down_revision is None:
                break
            current = script.get_revision(current.down_revision)
        revisions.reverse()
        return revisions

    def _run_alembic_command(
        self, connection: Connection, command_name: str, target: str
    ) -> None:
        from alembic import command
        from alembic.config import Config

        config = Config(str(self._alembic_ini_path()))
        config.set_main_option("sqlalchemy.url", self.database_url)
        config.attributes["connection"] = connection

        if command_name == "upgrade":
            command.upgrade(config, target)
        elif command_name == "downgrade":
            command.downgrade(config, target)
        else:
            raise ValueError(f"Unknown migration command: {command_name}")

        # Record the result in alembic_schema
        result = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).fetchone()
        if result is not None:
            rev = result[0]
            # For downgrade: copy the stored source from the matching upgrade row
            source_sql = (
                "INSERT INTO alembic_schema (version_num, direction, migration_source) "
                "SELECT :rev, :dir, migration_source FROM alembic_schema "
                "WHERE version_num = :rev2 AND direction = 'upgrade' "
                "ORDER BY id DESC LIMIT 1"
            )
            params = {"rev": rev, "dir": command_name, "rev2": rev}
            connection.execute(text(source_sql), params)

    def _get_script(self):
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(self._alembic_ini_path()))
        config.set_main_option("sqlalchemy.url", self.database_url)
        return ScriptDirectory.from_config(config)

    # ------------------------------------------------------------------
    # infrastructure
    # ------------------------------------------------------------------

    def _create_engine(self) -> Engine:
        return create_engine(self.database_url, future=True, pool_pre_ping=True)

    def _uses_mysql(self) -> bool:
        return self.database_url.startswith("mysql")

    def _acquire_named_lock(self, connection: Connection) -> bool:
        result = connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {
                "lock_name": self.lock_name,
                "timeout_seconds": self.lock_timeout_seconds,
            },
        ).scalar_one()
        if result != 1:
            self.logger.error("Could not acquire schema migration lock")
            raise SystemExit(1)
        self.logger.info("Schema migration lock acquired")
        return True

    def _release_named_lock(self, connection: Connection) -> None:
        connection.execute(
            text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": self.lock_name}
        )
        self.logger.info("Schema migration lock released")

    @staticmethod
    def _alembic_ini_path() -> Path:
        return Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migration() -> None:
    configure_bootstrap_logging(DEFAULT_LOG_LEVEL)
    settings = load_bootstrap_settings()
    SchemaMigrationRunner(database_url=settings.database_url).run()
