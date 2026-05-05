from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "amsz-task-service"
    app_env: str = "dev"
    log_level: str = "INFO"
    log_dir: str = str(Path("data"))
    log_file_name: str = "amsz-task-service.log"
    log_file_max_bytes: int = 50 * 1024 * 1024
    log_file_backup_count: int = 5

    api_host: str = "0.0.0.0"
    api_port: int = 8200
    api_key: str = ""

    database_url: str = Field(
        default="sqlite+pysqlite:///./amsz.db",
        description="MySQL example: mysql+pymysql://user:pass@host:3306/dbname",
    )
    auto_create_tables: bool = False

    worker_id: str = ""
    pod_name: str = "pod-local"
    worker_queue: str = "default"
    worker_concurrency: int = 2
    worker_poll_interval_seconds: float = 2.0
    worker_claim_batch_size: int = 5
    worker_lease_seconds: int = 30
    worker_heartbeat_interval_seconds: int = 10
    worker_recover_limit: int = 100
    task_fanout_shard_size: int = 2
    task_fanout_max_children: int = 10


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
