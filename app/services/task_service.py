from __future__ import annotations

from datetime import datetime

from app.core.config import get_settings
from app.core.app_logging import get_logger
from app.core.time import utc_now
from app.domain.enums import TaskRole, TaskStatus
from app.db.models import Task, TaskEvent
from app.repositories.task_repository import ChildTaskSpec, TaskRepository
from app.schemas.task import TaskCreateRequest

EXTERNAL_FANOUT_TASK_TYPE = "batch.sleep.echo"
INTERNAL_TASK_TYPES = {
    "batch.sleep.echo.shard",
    "batch.sleep.echo.aggregate",
}


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository
        self.settings = get_settings()
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
        if request.task_type in INTERNAL_TASK_TYPES:
            raise ValueError("Internal task types cannot be submitted directly")

        scheduled_at = request.scheduled_at or utc_now()
        if request.task_type == EXTERNAL_FANOUT_TASK_TYPE:
            return self._create_fanout_task(
                request=request,
                created_by=created_by,
                request_id=request_id,
                scheduled_at=scheduled_at,
            )

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

    def _create_fanout_task(
        self,
        *,
        request: TaskCreateRequest,
        created_by: str | None,
        request_id: str,
        scheduled_at: datetime,
    ) -> tuple[int, str, bool]:
        items = request.payload.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("batch.sleep.echo payload.items must be a non-empty list")

        shard_size = self.settings.task_fanout_shard_size
        shards = [
            items[index:index + shard_size]
            for index in range(0, len(items), shard_size)
        ]
        if len(shards) > self.settings.task_fanout_max_children:
            raise ValueError("Task fan-out exceeds configured child task limit")

        parent_task, created = self.repository.create_task(
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
            status=TaskStatus.DISPATCHING,
            task_role=TaskRole.PARENT,
            child_summary={},
        )
        if not created:
            return parent_task.id, parent_task.status.value, False

        child_specs = [
            ChildTaskSpec(
                task_type="batch.sleep.echo.shard",
                payload={"items": shard},
                shard_index=index,
                shard_key=f"shard-{index}",
                priority=request.priority,
            )
            for index, shard in enumerate(shards)
        ]
        self.repository.create_child_tasks(
            parent_task_id=parent_task.id,
            queue_name=request.queue_name,
            child_specs=child_specs,
            max_attempts=request.max_attempts,
            timeout_seconds=request.timeout_seconds,
            created_by=created_by,
        )
        parent_task = self.repository.transition_parent_to_running(
            parent_task.id,
            len(child_specs),
        )
        self.logger.info(
            "Fan-out task persisted",
            extra={"request_id": request_id, "task_id": parent_task.id, "worker_id": "-"},
        )
        return parent_task.id, parent_task.status.value, True

    def get_task(self, task_id: int) -> Task | None:
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
    ) -> list[Task]:
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

    def request_cancel(self, task_id: int) -> Task | None:
        return self.repository.request_cancel(task_id)

    def retry_task(self, task_id: int) -> Task | None:
        return self.repository.retry_task(task_id)

    def list_events(self, task_id: int) -> list[TaskEvent]:
        return self.repository.list_events(task_id)

    def list_children(self, task_id: int) -> list[Task]:
        return self.repository.list_children(task_id)
