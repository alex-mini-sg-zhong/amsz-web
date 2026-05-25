from __future__ import annotations

import logging
from pathlib import Path
import re

from fastapi.testclient import TestClient

from app.bootstrap.logging import configure_runtime_logging
from app.core.config import clear_settings_caches, get_settings
from app.core.app_logging import configure_logging
from app.infrastructure.datasource.relational.base import Base
from app.interfaces.http.app import create_app
from tests.conftest import seed_active_runtime_config


def test_configure_logging_supports_third_party_logger(caplog) -> None:
    configure_logging("INFO")

    with caplog.at_level(logging.INFO):
        logging.getLogger("uvicorn.error").info("startup complete")

    assert "startup complete" in caplog.text
    assert "request_id=-" in caplog.text
    assert "service=amsz-task-service" in caplog.text
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}", caplog.text)


def test_request_logging_uses_unified_fields(caplog) -> None:
    configure_logging("INFO")
    client = TestClient(create_app())

    with caplog.at_level(logging.INFO):
        response = client.get("/healthz")

    assert response.status_code == 200
    assert "logger=app.interfaces.http.request" in caplog.text
    assert "http_method=GET" in caplog.text
    assert "http_path=/healthz" in caplog.text
    assert "status_code=200" in caplog.text


def test_create_app_does_not_attempt_schema_creation(monkeypatch) -> None:
    def fail_create_all(*args, **kwargs) -> None:
        raise AssertionError("schema creation should not happen during app startup")

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)

    app = create_app()

    assert app.title == "amsz-task-service"


def test_alembic_logger_uses_unified_format(caplog) -> None:
    configure_logging("INFO")

    with caplog.at_level(logging.INFO):
        logging.getLogger("alembic.runtime.migration").info("migration started")

    assert "logger=alembic.runtime.migration" in caplog.text
    assert "message=migration started" in caplog.text


def test_configure_logging_writes_to_rotating_file(tmp_path) -> None:
    log_dir = tmp_path / "data"
    seed_active_runtime_config(
        {
            "log_dir": str(log_dir),
            "log_file_max_bytes": 256,
            "log_file_backup_count": 2,
        }
    )
    clear_settings_caches()

    configure_runtime_logging(get_settings())
    logger = logging.getLogger("test.rotating")

    for _ in range(40):
        logger.info("rotating-log-entry %s", "x" * 40)

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert (Path(log_dir) / "amsz-task-service.log").exists()
    rotated_files = list(Path(log_dir).glob("amsz-task-service.log.*"))
    assert rotated_files
