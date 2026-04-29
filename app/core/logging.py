from __future__ import annotations

import logging

from app.core.config import get_settings


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
    def format(self, record: logging.LogRecord) -> str:
        settings = get_settings()
        for field_name, default_value in DEFAULT_LOG_FIELDS.items():
            if not hasattr(record, field_name):
                setattr(record, field_name, default_value)
        if not hasattr(record, "service"):
            record.service = settings.app_name
        if not hasattr(record, "env"):
            record.env = settings.app_env
        return super().format(record)


def configure_logging(level: str) -> None:
    settings = get_settings()
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
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    root_logger.setLevel(level.upper())

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        return

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        extra = kwargs.setdefault("extra", {})
        merged = dict(DEFAULT_LOG_FIELDS)
        merged["service"] = get_settings().app_name
        merged["env"] = get_settings().app_env
        merged.update(self.extra)
        merged.update(extra)
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(name: str, **context: str | int | None) -> ContextAdapter:
    normalized = {
        key: value if value is not None else "-"
        for key, value in context.items()
    }
    normalized.setdefault("service", get_settings().app_name)
    normalized.setdefault("env", get_settings().app_env)
    return ContextAdapter(logging.getLogger(name), normalized)
