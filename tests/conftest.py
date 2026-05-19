from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.config import clear_settings_caches, default_runtime_config_template
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import get_engine, get_session_factory, session_scope
from app.repositories.runtime_config_repository import RuntimeConfigRepository


def seed_active_runtime_config(overrides: dict[str, Any] | None = None) -> None:
    template = default_runtime_config_template()
    if overrides:
        template.update(overrides)

    with session_scope() as session:
        repository = RuntimeConfigRepository(session)
        revision = repository.create_revision(
            config_json=template,
            created_by="test-suite",
            change_note="seed runtime config",
            schema_version=1,
            base_revision_id=None,
        )
        repository.activate_revision(revision_id=revision.id, published_by="test-suite")

    clear_settings_caches()


@pytest.fixture(autouse=True)
def reset_settings(tmp_path) -> Generator[None, None, None]:
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["API_KEY"] = "test-key"
    os.environ["WORKER_ID"] = "worker-test"
    os.environ["POD_NAME"] = "pod-test"
    os.environ["APP_ENV"] = "test"
    os.environ["WORKER_QUEUE"] = "default"
    os.environ["WORKER_CONCURRENCY"] = "2"
    clear_settings_caches()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    Base.metadata.create_all(bind=get_engine())
    seed_active_runtime_config()
    yield
    clear_settings_caches()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
