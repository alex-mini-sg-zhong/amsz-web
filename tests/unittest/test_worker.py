from __future__ import annotations

from app.core.config import get_settings
from app.db.session import session_scope
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreateRequest
from app.services.task_service import TaskService
from app.worker.runner import WorkerRunner


def test_worker_executes_task() -> None:
    with session_scope() as session:
        service = TaskService(TaskRepository(session))
        task_id, _, _ = service.create_task(
            TaskCreateRequest(
                task_type="noop.success",
                queue_name="default",
                payload={"echo": "worker"},
            ),
            created_by="tester",
            request_id="req-1",
        )

    runner = WorkerRunner(queue_name="default", concurrency=1)
    claimed = runner.run_once(wait_for_completion=True)
    assert claimed == 1

    with session_scope() as session:
        task = TaskRepository(session).get_task(task_id)
        assert task is not None
        assert task.status.value == "SUCCEEDED"
        assert task.result_json == {"accepted": True, "echo": "worker"}


def test_worker_moves_retryable_task_to_retry_wait() -> None:
    with session_scope() as session:
        service = TaskService(TaskRepository(session))
        task_id, _, _ = service.create_task(
            TaskCreateRequest(
                task_type="force.retry",
                queue_name="default",
                max_attempts=2,
                payload={},
            ),
            created_by="tester",
            request_id="req-2",
        )

    runner = WorkerRunner(queue_name="default", concurrency=1)
    runner.run_once(wait_for_completion=True)

    with session_scope() as session:
        task = TaskRepository(session).get_task(task_id)
        assert task is not None
        assert task.status.value == "RETRY_WAIT"


def test_worker_runner_defaults_worker_id_from_pod_name(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_ID", "")
    monkeypatch.setenv("POD_NAME", "pod-runtime")
    get_settings.cache_clear()

    runner = WorkerRunner(queue_name="default", concurrency=1)

    assert runner.worker_id == "pod-runtime-worker"
