from __future__ import annotations

from app.db.session import session_scope
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
