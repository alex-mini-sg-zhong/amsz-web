from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "amsz-task-service"
DEFAULT_LOG_LEVEL = "INFO"
PLACEHOLDER_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")
ALLOWED_PLACEHOLDER_ENV_NAMES = {
    "API_KEY",
    "WORKER_ID",
    "POD_NAME",
    "APP_ENV",
    "WORKER_QUEUE",
    "WORKER_CONCURRENCY",
}
SECRET_FIELD_NAMES = {"api_key"}


class RuntimeConfigError(RuntimeError):
    """Raised when runtime configuration cannot be loaded or validated."""


class BootstrapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)
    database_url: str = Field(default="sqlite+pysqlite:///./amsz.db", description="MySQL example: mysql+pymysql://user:pass@host:3306/dbname")


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str = APP_NAME
    app_env: str = "dev"
    log_level: str = DEFAULT_LOG_LEVEL
    log_dir: str = str(Path("data"))
    log_file_name: str = "amsz-task-service.log"
    log_file_max_bytes: int = 50 * 1024 * 1024
    log_file_backup_count: int = 5
    api_host: str = "0.0.0.0"
    api_port: int = 8200
    api_key: str
    worker_id: str
    pod_name: str
    worker_queue: str = "default"
    worker_profile: str = "default"
    worker_concurrency: int = 2
    worker_poll_interval_seconds: float = 2.0
    worker_claim_batch_size: int = 5
    worker_lease_seconds: int = 30
    worker_heartbeat_interval_seconds: int = 10
    worker_recover_limit: int = 100
    task_fanout_shard_size: int = 2
    task_fanout_max_children: int = 10
    scheduler_enabled: bool = True
    scheduler_tick_interval_seconds: float = 10.0
    scheduler_max_due_schedules: int = 10
    polymarket_base_url: str = "https://gamma-api.polymarket.com"
    polymarket_request_timeout_seconds: float = 10.0
    polymarket_catalog_limit: int = 200
    polymarket_snapshot_limit: int = 100


class LoggingSettings(BaseModel):
    app_name: str = APP_NAME
    app_env: str = "bootstrap"
    log_dir: str = str(Path("data"))
    log_file_name: str = "amsz-task-service.log"
    log_file_max_bytes: int = 50 * 1024 * 1024
    log_file_backup_count: int = 5


def default_runtime_config_template() -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "app_env": "${APP_ENV}",
        "log_level": DEFAULT_LOG_LEVEL,
        "log_dir": "data",
        "log_file_name": "amsz-task-service.log",
        "log_file_max_bytes": 50 * 1024 * 1024,
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
    }


@lru_cache(maxsize=1)
def get_bootstrap_settings() -> BootstrapSettings:
    return BootstrapSettings()


@lru_cache(maxsize=1)
def get_settings() -> RuntimeSettings:
    from app.infrastructure.datasource.relational.session import session_scope
    from app.infrastructure.repositories.runtime_config_repository import RuntimeConfigRepository

    with session_scope() as session:
        repository = RuntimeConfigRepository(session)
        revision = repository.get_active_revision()
        if revision is None:
            raise RuntimeConfigError("No active runtime configuration revision found")
        template = repository.get_revision_config(revision.id)
    return build_runtime_settings(template)


def build_runtime_settings(template: dict[str, Any]) -> RuntimeSettings:
    validate_runtime_config_template(template)
    resolved = resolve_config_placeholders(template)
    try:
        return RuntimeSettings.model_validate(resolved)
    except Exception as exc:  # pragma: no cover
        raise RuntimeConfigError(f"Runtime configuration validation failed: {exc}") from exc


def validate_runtime_config_template(template: dict[str, Any]) -> None:
    for field_name, value in template.items():
        _validate_template_value(field_name, value)
    for field_name in SECRET_FIELD_NAMES:
        if field_name not in template:
            raise RuntimeConfigError(f"Sensitive field '{field_name}' is missing from template")


def resolve_config_placeholders(template: dict[str, Any]) -> dict[str, Any]:
    return {key: _resolve_template_value(value) for key, value in template.items()}


def get_logging_settings() -> LoggingSettings:
    try:
        settings = get_settings()
        return LoggingSettings(
            app_name=settings.app_name,
            app_env=settings.app_env,
            log_dir=settings.log_dir,
            log_file_name=settings.log_file_name,
            log_file_max_bytes=settings.log_file_max_bytes,
            log_file_backup_count=settings.log_file_backup_count,
        )
    except RuntimeConfigError:
        return LoggingSettings()


def clear_settings_caches() -> None:
    get_bootstrap_settings.cache_clear()
    get_settings.cache_clear()


def _validate_template_value(field_name: str, value: Any) -> None:
    if isinstance(value, dict):
        for nested_name, nested_value in value.items():
            _validate_template_value(nested_name, nested_value)
        return
    if isinstance(value, list):
        for nested_value in value:
            _validate_template_value(field_name, nested_value)
        return
    if not isinstance(value, str):
        return

    match = PLACEHOLDER_PATTERN.fullmatch(value)
    if match:
        env_name = match.group(1)
        if env_name not in ALLOWED_PLACEHOLDER_ENV_NAMES:
            raise RuntimeConfigError(f"Placeholder '{env_name}' is not allowed")
        return

    if "${" in value:
        raise RuntimeConfigError(f"Field '{field_name}' contains an invalid placeholder expression")

    if field_name in SECRET_FIELD_NAMES and value:
        raise RuntimeConfigError(f"Sensitive field '{field_name}' must use a placeholder")


def _resolve_template_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {nested_key: _resolve_template_value(nested_value) for nested_key, nested_value in value.items()}
    if isinstance(value, list):
        return [_resolve_template_value(item) for item in value]
    if not isinstance(value, str):
        return value

    match = PLACEHOLDER_PATTERN.fullmatch(value)
    if not match:
        if "${" in value:
            raise RuntimeConfigError("Only full-value placeholders are supported")
        return value

    env_name = match.group(1)
    if env_name not in ALLOWED_PLACEHOLDER_ENV_NAMES:
        raise RuntimeConfigError(f"Placeholder '{env_name}' is not allowed")

    env_value = os.getenv(env_name)
    if env_value is None or env_value == "":
        raise RuntimeConfigError(f"Environment variable '{env_name}' is required")
    return env_value
