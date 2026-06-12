from __future__ import annotations

from datetime import datetime
from typing import Any

from app.infrastructure.datasource.relational.session import session_scope
from app.domain.enums import AttemptStatus, TaskRole
from app.infrastructure.repositories.task_repository import ClaimedTask, TaskRepository

AGGREGATE_TASK_TYPE = "batch.sleep.echo.aggregate"


class TaskExecutionService:
    def mark_task_succeeded(
        self,
        *,
        task: ClaimedTask,
        worker_id: str,
        result: dict[str, Any] | None,
    ) -> None:
        aggregate_created_by: str | None = None
        with session_scope() as session:
            repository = TaskRepository(session)
            completed_task = repository.mark_succeeded(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=worker_id,
                result=result,
            )
            aggregate_created_by = completed_task.created_by
        self._handle_post_success(task=task, result=result, aggregate_created_by=aggregate_created_by)

    def mark_task_retry_wait(
        self,
        *,
        task: ClaimedTask,
        worker_id: str,
        error_code: str,
        error_message: str,
        scheduled_at: datetime,
    ) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_retry_wait(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=worker_id,
                error_code=error_code,
                error_message=error_message,
                scheduled_at=scheduled_at,
            )
        if task.task_type.startswith("szdm."):
            return
        self._handle_post_child_update(task)

    def mark_task_failed(
        self,
        *,
        task: ClaimedTask,
        worker_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_failed(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=worker_id,
                error_code=error_code,
                error_message=error_message,
                attempt_status=AttemptStatus.FAILED,
            )
        self._handle_post_failure(task, error_code, error_message)

    def mark_task_dead(
        self,
        *,
        task: ClaimedTask,
        worker_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_dead(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=worker_id,
                error_code=error_code,
                error_message=error_message,
            )
        self._handle_post_failure(task, error_code, error_message)

    def mark_task_canceled(self, *, task: ClaimedTask, worker_id: str) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_canceled(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=worker_id,
            )
        if task.task_type.startswith("szdm."):
            return
        self._handle_post_child_update(task)

    def update_progress(
        self,
        *,
        task_id: int,
        worker_id: str,
        progress: int,
        current_stage: str | None,
    ) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.update_progress(
                task_id=task_id,
                worker_id=worker_id,
                progress=progress,
                current_stage=current_stage,
            )

    def is_cancel_requested(self, task_id: int, parent_task_id: int | None) -> bool:
        with session_scope() as session:
            repository = TaskRepository(session)
            return repository.is_cancel_requested(task_id, parent_task_id)

    def load_child_results(self, parent_task_id: int) -> list[dict[str, Any]]:
        with session_scope() as session:
            repository = TaskRepository(session)
            return repository.load_child_results(parent_task_id)

    def _handle_post_success(
        self,
        *,
        task: ClaimedTask,
        result: dict[str, Any] | None,
        aggregate_created_by: str | None,
    ) -> None:
        if task.task_type.startswith("szdm."):
            return

        if task.task_role == TaskRole.CHILD and task.parent_task_id is not None:
            self._handle_post_child_update(task, aggregate_created_by=aggregate_created_by)
            return

        if task.task_role == TaskRole.AGGREGATE and task.parent_task_id is not None:
            with session_scope() as session:
                repository = TaskRepository(session)
                repository.mark_parent_succeeded(
                    parent_task_id=task.parent_task_id,
                    result=result,
                )

    def _handle_post_failure(
        self,
        task: ClaimedTask,
        error_code: str,
        error_message: str,
    ) -> None:
        if task.task_type.startswith("szdm."):
            return

        if task.task_role == TaskRole.CHILD and task.parent_task_id is not None:
            self._handle_post_child_update(task)
            return

        if task.task_role == TaskRole.AGGREGATE and task.parent_task_id is not None:
            with session_scope() as session:
                repository = TaskRepository(session)
                repository.mark_parent_failed(
                    parent_task_id=task.parent_task_id,
                    error_code=error_code,
                    error_message=error_message,
                )

    def _handle_post_child_update(
        self,
        task: ClaimedTask,
        aggregate_created_by: str | None = None,
    ) -> None:
        if task.task_role == TaskRole.CHILD and task.parent_task_id is not None:
            with session_scope() as session:
                repository = TaskRepository(session)
                repository.refresh_parent_state(task.parent_task_id)
                if aggregate_created_by is not None:
                    repository.schedule_aggregate_task_if_ready(
                        parent_task_id=task.parent_task_id,
                        aggregate_task_type=AGGREGATE_TASK_TYPE,
                        queue_name=task.queue_name,
                        priority=task.priority,
                        max_attempts=task.max_attempts,
                        timeout_seconds=task.timeout_seconds,
                        created_by=aggregate_created_by,
                    )
