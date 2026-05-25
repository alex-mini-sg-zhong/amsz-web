from __future__ import annotations

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

    def run(self) -> None:
        self.logger.info("Starting schema migration")
        engine = self._create_engine()
        try:
            with engine.connect() as connection:
                lock_acquired = False
                if self._uses_mysql():
                    lock_acquired = self._acquire_named_lock(connection)
                try:
                    self._run_upgrade(connection)
                    self.logger.info("Schema migration completed")
                finally:
                    if lock_acquired:
                        self._release_named_lock(connection)
                connection.commit()
        finally:
            engine.dispose()

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
        connection.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": self.lock_name})
        self.logger.info("Schema migration lock released")

    def _run_upgrade(self, connection: Connection) -> None:
        from alembic import command
        from alembic.config import Config

        config = Config(str(self._alembic_ini_path()))
        config.set_main_option("sqlalchemy.url", self.database_url)
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    @staticmethod
    def _alembic_ini_path() -> Path:
        return Path(__file__).resolve().parents[2] / "alembic.ini"


def run_migration() -> None:
    configure_bootstrap_logging(DEFAULT_LOG_LEVEL)
    settings = load_bootstrap_settings()
    SchemaMigrationRunner(database_url=settings.database_url).run()
