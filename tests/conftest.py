from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import get_engine, get_session_factory


@pytest.fixture(autouse=True)
def reset_settings(tmp_path) -> Generator[None, None, None]:
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["AUTO_CREATE_TABLES"] = "false"
    os.environ["API_KEY"] = "test-key"
    os.environ["WORKER_ID"] = "worker-test"
    os.environ["POD_NAME"] = "pod-test"
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    Base.metadata.create_all(bind=get_engine())
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
