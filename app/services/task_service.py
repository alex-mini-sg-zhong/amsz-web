from __future__ import annotations

from app.core.app_logging import get_logger
from app.core.time import utc_now
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreateRequest


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository
        self.logger = get_logger("app.services.task_service")

    def create_task(
        self,
        request: TaskCreateRequest,
        created_by: str | None,
        request_id: str,
    ) -> tuple[int, str, bool]:
        self.logger.info(
            "Creating task",
            extra={
                "request_id": request_id,
                "task_id": "-",
                "worker_id": "-",
            },
        )
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

    def get_task(self, task_id: int):
        return self.repository.get_task(task_id)

    def list_tasks(
        self,
        *,
        status: str | None,
        task_type: str | None,
        queue_name: str | None,
        biz_key: str | None,
        page: int,
        page_size: int,
    ):
        limit = page_size
        offset = (page - 1) * page_size
        return self.repository.list_tasks(
            status=status,
            task_type=task_type,
            queue_name=queue_name,
            biz_key=biz_key,
            limit=limit,
            offset=offset,
        )

    def request_cancel(self, task_id: int):
        return self.repository.request_cancel(task_id)

    def retry_task(self, task_id: int):
        return self.repository.retry_task(task_id)

    def list_events(self, task_id: int):
        return self.repository.list_events(task_id)
