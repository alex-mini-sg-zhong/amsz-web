from __future__ import annotations

from app.infrastructure.datasource.relational.models import Task, TaskEvent
from app.infrastructure.repositories.task_repository import TaskRepository


class TaskQueryService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

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

    def list_events(self, task_id: int) -> list[TaskEvent]:
        return self.repository.list_events(task_id)

    def list_children(self, task_id: int) -> list[Task]:
        return self.repository.list_children(task_id)
