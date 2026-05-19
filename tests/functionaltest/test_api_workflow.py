from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.api.app import create_app
from app.core.config import clear_settings_caches
from app.db.session import get_engine, get_session_factory, session_scope
from app.repositories.task_repository import TaskRepository
from app.worker.runner import WorkerRunner


def test_create_and_get_task(client) -> None:
    response = client.post(
        "/api/v1/tasks",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "task_type": "noop.success",
            "queue_name": "default",
            "idempotency_key": "idem-1",
            "payload": {"echo": "hello"},
        },
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    detail = client.get(f"/api/v1/tasks/{task_id}", headers={"X-API-Key": "test-key"})
    assert detail.status_code == 200
    assert detail.json()["status"] == "PENDING"


def test_idempotency_returns_existing_task(client) -> None:
    payload = {
        "task_type": "noop.success",
        "queue_name": "default",
        "idempotency_key": "idem-2",
        "payload": {"echo": "hello"},
    }
    first = client.post("/api/v1/tasks", headers={"X-API-Key": "test-key"}, json=payload)
    second = client.post("/api/v1/tasks", headers={"X-API-Key": "test-key"}, json=payload)

    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["task_id"] == second.json()["task_id"]


def test_cancel_pending_task(client) -> None:
    create_response = client.post(
        "/api/v1/tasks",
        headers={"X-API-Key": "test-key"},
        json={
            "task_type": "noop.success",
            "queue_name": "default",
            "payload": {"echo": "hello"},
        },
    )
    task_id = create_response.json()["task_id"]

    cancel_response = client.post(
        f"/api/v1/tasks/{task_id}/cancel",
        headers={"X-API-Key": "test-key"},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELED"


def test_submit_then_worker_executes_task(client) -> None:
    create_response = client.post(
        "/api/v1/tasks",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "task_type": "noop.success",
            "queue_name": "default",
            "payload": {"echo": "functional"},
        },
    )
    assert create_response.status_code == 202
    task_id = create_response.json()["task_id"]

    runner = WorkerRunner(queue_name="default", concurrency=1)
    claimed = runner.run_once(wait_for_completion=True)
    assert claimed == 1

    detail = client.get(f"/api/v1/tasks/{task_id}", headers={"X-API-Key": "test-key"})
    assert detail.status_code == 200
    assert detail.json()["status"] == "SUCCEEDED"
    assert detail.json()["result"] == {"accepted": True, "echo": "functional"}

    with session_scope() as session:
        task = TaskRepository(session).get_task(task_id)
        assert task is not None
        assert task.lease_owner is None


def test_batch_task_creates_children_and_aggregates(client) -> None:
    create_response = client.post(
        "/api/v1/tasks",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "task_type": "batch.sleep.echo",
            "queue_name": "default",
            "payload": {
                "items": [
                    {"seconds": 0, "echo": "a"},
                    {"seconds": 0, "echo": "b"},
                    {"seconds": 0, "echo": "c"},
                ]
            },
        },
    )
    assert create_response.status_code == 202
    parent_task_id = create_response.json()["task_id"]
    assert create_response.json()["status"] == "PARTIALLY_RUNNING"

    detail = client.get(
        f"/api/v1/tasks/{parent_task_id}",
        headers={"X-API-Key": "test-key"},
    )
    assert detail.status_code == 200
    assert detail.json()["total_children"] == 2
    assert detail.json()["task_role"] == "parent"

    children_response = client.get(
        f"/api/v1/tasks/{parent_task_id}/children",
        headers={"X-API-Key": "test-key"},
    )
    assert children_response.status_code == 200
    assert len(children_response.json()) == 2

    runner = WorkerRunner(queue_name="default", concurrency=2)
    first_batch = runner.run_once(wait_for_completion=True)
    second_batch = runner.run_once(wait_for_completion=True)
    assert first_batch == 2
    assert second_batch == 1

    final_detail = client.get(
        f"/api/v1/tasks/{parent_task_id}",
        headers={"X-API-Key": "test-key"},
    )
    assert final_detail.status_code == 200
    assert final_detail.json()["status"] == "SUCCEEDED"
    assert final_detail.json()["succeeded_children"] == 2
    assert final_detail.json()["failed_children"] == 0
    assert final_detail.json()["running_children"] == 0
    assert final_detail.json()["result"]["total_items"] == 3

    final_children = client.get(
        f"/api/v1/tasks/{parent_task_id}/children",
        headers={"X-API-Key": "test-key"},
    )
    assert len(final_children.json()) == 3
    assert final_children.json()[-1]["task_role"] == "aggregate"


def test_batch_task_failure_marks_parent_failed(client) -> None:
    create_response = client.post(
        "/api/v1/tasks",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "task_type": "batch.sleep.echo",
            "queue_name": "default",
            "payload": {
                "items": [
                    {"seconds": -1, "echo": "bad"},
                    {"seconds": 0, "echo": "good"},
                ]
            },
        },
    )
    assert create_response.status_code == 202
    parent_task_id = create_response.json()["task_id"]

    runner = WorkerRunner(queue_name="default", concurrency=1)
    runner.run_once(wait_for_completion=True)

    detail = client.get(
        f"/api/v1/tasks/{parent_task_id}",
        headers={"X-API-Key": "test-key"},
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "FAILED"
    assert detail.json()["failed_children"] == 1


def test_internal_task_type_cannot_be_submitted(client) -> None:
    response = client.post(
        "/api/v1/tasks",
        headers={"X-API-Key": "test-key"},
        json={
            "task_type": "batch.sleep.echo.shard",
            "queue_name": "default",
            "payload": {"items": [{"seconds": 0, "echo": "hello"}]},
        },
    )

    assert response.status_code == 400


def test_get_active_runtime_config(client) -> None:
    response = client.get(
        "/api/v1/admin/runtime-config/active",
        headers={"X-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    assert response.json()["config"]["api_key"] == "${API_KEY}"
    assert response.json()["resolved_config"]["api_key"] == "test-key"


def test_create_and_activate_runtime_config_revision(client) -> None:
    active = client.get(
        "/api/v1/admin/runtime-config/active",
        headers={"X-API-Key": "test-key"},
    )
    base_revision_id = active.json()["revision_id"]
    config = active.json()["config"]
    config["task_fanout_shard_size"] = 3

    create_response = client.post(
        "/api/v1/admin/runtime-config/revisions",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "config": config,
            "change_note": "increase shard size",
            "base_revision_id": base_revision_id,
        },
    )
    assert create_response.status_code == 201
    revision_id = create_response.json()["revision_id"]
    assert create_response.json()["status"] == "DRAFT"

    activate_response = client.post(
        f"/api/v1/admin/runtime-config/revisions/{revision_id}/activate",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
    )
    assert activate_response.status_code == 200

    active_after = client.get(
        "/api/v1/admin/runtime-config/active",
        headers={"X-API-Key": "test-key"},
    )
    assert active_after.status_code == 200
    assert active_after.json()["revision_id"] == revision_id
    assert active_after.json()["resolved_config"]["task_fanout_shard_size"] == 3


def test_plaintext_secret_field_is_rejected(client) -> None:
    response = client.post(
        "/api/v1/admin/runtime-config/revisions",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "config": {
                "app_name": "amsz-task-service",
                "app_env": "${APP_ENV}",
                "log_level": "INFO",
                "log_dir": "data",
                "log_file_name": "amsz-task-service.log",
                "log_file_max_bytes": 52428800,
                "log_file_backup_count": 5,
                "api_host": "0.0.0.0",
                "api_port": 8200,
                "api_key": "plaintext-secret",
                "worker_id": "${WORKER_ID}",
                "pod_name": "${POD_NAME}",
                "worker_queue": "${WORKER_QUEUE}",
                "worker_concurrency": "${WORKER_CONCURRENCY}",
                "worker_poll_interval_seconds": 2.0,
                "worker_claim_batch_size": 5,
                "worker_lease_seconds": 30,
                "worker_heartbeat_interval_seconds": 10,
                "worker_recover_limit": 100,
                "task_fanout_shard_size": 2,
                "task_fanout_max_children": 10,
            }
        },
    )

    assert response.status_code == 400
    assert "Sensitive field 'api_key'" in response.json()["detail"]


def test_missing_schema_does_not_trigger_implicit_creation(monkeypatch, tmp_path) -> None:
    empty_db_path = tmp_path / "empty.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{empty_db_path}")
    clear_settings_caches()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    with pytest.raises(SQLAlchemyError):
        create_app()

    with sqlite3.connect(empty_db_path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert tables == []
