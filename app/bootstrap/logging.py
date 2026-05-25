from __future__ import annotations

from app.core.app_logging import configure_logging
from app.core.config import DEFAULT_LOG_LEVEL, LoggingSettings, RuntimeSettings


def configure_bootstrap_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    configure_logging(level, LoggingSettings())


def configure_runtime_logging(settings: RuntimeSettings) -> None:
    configure_logging(
        settings.log_level or DEFAULT_LOG_LEVEL,
        LoggingSettings(
            app_name=settings.app_name,
            app_env=settings.app_env,
            log_dir=settings.log_dir,
            log_file_name=settings.log_file_name,
            log_file_max_bytes=settings.log_file_max_bytes,
            log_file_backup_count=settings.log_file_backup_count,
        ),
    )
