from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_logging_settings

CONSOLE_HANDLER_NAME = "amsz_console"
FILE_HANDLER_NAME = "amsz_file"

DEFAULT_LOG_FIELDS = {
    "request_id": "-",
    "task_id": "-",
    "worker_id": "-",
    "http_method": "-",
    "http_path": "-",
    "status_code": "-",
    "duration_ms": "-",
    "client_ip": "-",
}


class DefaultContextFormatter(logging.Formatter):
    def formatTime(
        self,
        record: logging.LogRecord,
        datefmt: str | None = None,
    ) -> str:
        timestamp = datetime.fromtimestamp(record.created).astimezone()
        return timestamp.isoformat(timespec="milliseconds")

    def format(self, record: logging.LogRecord) -> str:
        settings = get_logging_settings()
        for field_name, default_value in DEFAULT_LOG_FIELDS.items():
            if not hasattr(record, field_name):
                setattr(record, field_name, default_value)
        if not hasattr(record, "service"):
            record.service = settings.app_name
        if not hasattr(record, "env"):
            record.env = settings.app_env
        return super().format(record)


def configure_logging(level: str) -> None:
    settings = get_logging_settings()
    root_logger = logging.getLogger()
    formatter = DefaultContextFormatter(
        fmt=(
            "%(asctime)s "
            "level=%(levelname)s "
            "logger=%(name)s "
            "service=%(service)s "
            "env=%(env)s "
            "request_id=%(request_id)s "
            "task_id=%(task_id)s "
            "worker_id=%(worker_id)s "
            "http_method=%(http_method)s "
            "http_path=%(http_path)s "
            "status_code=%(status_code)s "
            "duration_ms=%(duration_ms)s "
            "client_ip=%(client_ip)s "
            "message=%(message)s"
        ),
    )
    root_logger.setLevel(level.upper())

    _configure_console_handler(root_logger, formatter)
    _configure_file_handler(root_logger, formatter, settings)

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "alembic",
        "alembic.runtime.migration",
    ):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True


def _configure_console_handler(
    root_logger: logging.Logger,
    formatter: logging.Formatter,
) -> None:
    handler = _find_named_handler(root_logger, CONSOLE_HANDLER_NAME)
    if handler is None:
        handler = logging.StreamHandler()
        handler.name = CONSOLE_HANDLER_NAME
        root_logger.addHandler(handler)
    handler.setFormatter(formatter)


def _configure_file_handler(
    root_logger: logging.Logger,
    formatter: logging.Formatter,
    settings,
) -> None:
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / settings.log_file_name

    existing_handler = _find_named_handler(root_logger, FILE_HANDLER_NAME)
    expected_filename = str(log_file_path.resolve())
    if isinstance(existing_handler, RotatingFileHandler):
        if existing_handler.baseFilename != expected_filename:
            root_logger.removeHandler(existing_handler)
            existing_handler.close()
            existing_handler = None

    if existing_handler is None:
        existing_handler = RotatingFileHandler(
            filename=log_file_path,
            maxBytes=settings.log_file_max_bytes,
            backupCount=settings.log_file_backup_count,
            encoding="utf-8",
        )
        existing_handler.name = FILE_HANDLER_NAME
        root_logger.addHandler(existing_handler)

    existing_handler.setFormatter(formatter)


def _find_named_handler(
    root_logger: logging.Logger,
    name: str,
) -> logging.Handler | None:
    for handler in root_logger.handlers:
        if handler.name == name:
            return handler
    return None


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        extra = kwargs.setdefault("extra", {})
        merged = dict(DEFAULT_LOG_FIELDS)
        settings = get_logging_settings()
        merged["service"] = settings.app_name
        merged["env"] = settings.app_env
        merged.update(self.extra)
        merged.update(extra)
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(name: str, **context: str | int | None) -> ContextAdapter:
    normalized = {
        key: value if value is not None else "-"
        for key, value in context.items()
    }
    settings = get_logging_settings()
    normalized.setdefault("service", settings.app_name)
    normalized.setdefault("env", settings.app_env)
    return ContextAdapter(logging.getLogger(name), normalized)
