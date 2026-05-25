from __future__ import annotations

import pytest

from app.application.services.base.task_command_service import TaskCommandService
from app.contracts.http.task import TaskCreateRequest
from app.core.config import clear_settings_caches
from app.infrastructure.datasource.relational.base import Base
from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.repositories.task_repository import TaskRepository
from app.infrastructure.runtime.worker_runner import WorkerRunner


def test_worker_executes_task() -> None:
    with session_scope() as session:
        service = TaskCommandService(TaskRepository(session))
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
        service = TaskCommandService(TaskRepository(session))
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


def test_worker_runner_uses_runtime_worker_id() -> None:
    clear_settings_caches()

    runner = WorkerRunner(queue_name="default", concurrency=1)

    assert runner.worker_id == "worker-test"


def test_worker_run_forever_does_not_attempt_schema_creation(monkeypatch) -> None:
    def fail_create_all(*args, **kwargs) -> None:
        raise AssertionError("schema creation should not happen during worker startup")

    def stop_runner(wait_for_completion: bool = False) -> int:
        raise RuntimeError("stop-loop")

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)
    runner = WorkerRunner(queue_name="default", concurrency=1)
    monkeypatch.setattr(runner, "run_once", stop_runner)

    with pytest.raises(RuntimeError, match="stop-loop"):
        runner.run_forever()



def test_worker_runner_uses_runtime_worker_profile(monkeypatch) -> None:
    from tests.conftest import seed_active_runtime_config

    seed_active_runtime_config({"worker_profile": "basic"})
    clear_settings_caches()

    runner = WorkerRunner(queue_name="default", concurrency=1)

    assert runner.worker_profile == "basic"
    assert "noop.success" in runner.handler_registry
    assert "batch.sleep.echo.shard" not in runner.handler_registry
