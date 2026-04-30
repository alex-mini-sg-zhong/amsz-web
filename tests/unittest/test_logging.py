from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.db.base import Base
from app.core.logging import configure_logging


def test_configure_logging_supports_third_party_logger(caplog) -> None:
    configure_logging("INFO")

    with caplog.at_level(logging.INFO):
        logging.getLogger("uvicorn.error").info("startup complete")

    assert "startup complete" in caplog.text
    assert "request_id=-" in caplog.text
    assert "service=amsz-task-service" in caplog.text


def test_request_logging_uses_unified_fields(caplog) -> None:
    configure_logging("INFO")
    client = TestClient(create_app())

    with caplog.at_level(logging.INFO):
        response = client.get("/healthz")

    assert response.status_code == 200
    assert "logger=app.api.request" in caplog.text
    assert "http_method=GET" in caplog.text
    assert "http_path=/healthz" in caplog.text
    assert "status_code=200" in caplog.text


def test_create_app_does_not_attempt_schema_creation(monkeypatch) -> None:
    def fail_create_all(*args, **kwargs) -> None:
        raise AssertionError("schema creation should not happen during app startup")

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)

    app = create_app()

    assert app.title == "amsz-task-service"
