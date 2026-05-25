from __future__ import annotations

from app.core.app_logging import get_logger
from app.core.time import utc_now
from app.infrastructure.datasource.relational.models import Task
from app.infrastructure.repositories.task_repository import TaskRepository
from app.contracts.http.task import TaskCreateRequest
from app.application.services.aggregate.task_orchestration_service import (
    EXTERNAL_FANOUT_TASK_TYPE,
    INTERNAL_TASK_TYPES,
)


class TaskCommandService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository
        self.logger = get_logger("app.application.services.base.task_command")

    def create_task(
        self,
        request: TaskCreateRequest,
        created_by: str | None,
        request_id: str,
    ) -> tuple[int, str, bool]:
        self.logger.info(
            "Creating task",
            extra={"request_id": request_id, "task_id": "-", "worker_id": "-"},
        )
        if request.task_type in INTERNAL_TASK_TYPES:
            raise ValueError("Internal task types cannot be submitted directly")
        if request.task_type == EXTERNAL_FANOUT_TASK_TYPE:
            raise ValueError("Fan-out task type must be handled by orchestration service")

        scheduled_at = request.scheduled_at or utc_now()
        task, created = self.repository.create_task(
            task_type=request.task_type,
            queue_name=request.queue_name,
            biz_key=request.biz_key,
            idempotency_key=request.idempotency_key,
            priority=request.priority,
            max_attempts=request.max_attempts,
            timeout_seconds=request.timeout_seconds,
            scheduled_at=scheduled_at,
            payload=request.payload,
            created_by=created_by,
        )
        self.logger.info(
            "Task persisted",
            extra={"request_id": request_id, "task_id": task.id, "worker_id": "-"},
        )
        return task.id, task.status.value, created

    def request_cancel(self, task_id: int) -> Task | None:
        return self.repository.request_cancel(task_id)

    def retry_task(self, task_id: int) -> Task | None:
        return self.repository.retry_task(task_id)
