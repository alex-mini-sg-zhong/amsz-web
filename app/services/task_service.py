from __future__ import annotations

from app.application.services.aggregate.task_orchestration_service import (
    EXTERNAL_FANOUT_TASK_TYPE,
    INTERNAL_TASK_TYPES,
    TaskOrchestrationService,
)
from app.application.services.base.task_command_service import TaskCommandService
from app.application.services.base.task_query_service import TaskQueryService
from app.infrastructure.repositories.task_repository import TaskRepository
from app.contracts.http.task import TaskCreateRequest


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.command_service = TaskCommandService(repository)
        self.query_service = TaskQueryService(repository)
        self.orchestration_service = TaskOrchestrationService(repository)

    def create_task(
        self,
        request: TaskCreateRequest,
        created_by: str | None,
        request_id: str,
    ) -> tuple[int, str, bool]:
        if request.task_type in INTERNAL_TASK_TYPES:
            raise ValueError("Internal task types cannot be submitted directly")
        if request.task_type == EXTERNAL_FANOUT_TASK_TYPE:
            return self.orchestration_service.create_fanout_task(request, created_by, request_id)
        return self.command_service.create_task(request, created_by, request_id)

    def get_task(self, task_id: int):
        return self.query_service.get_task(task_id)

    def list_tasks(self, **kwargs):
        return self.query_service.list_tasks(**kwargs)

    def request_cancel(self, task_id: int):
        return self.command_service.request_cancel(task_id)

    def retry_task(self, task_id: int):
        return self.command_service.retry_task(task_id)

    def list_events(self, task_id: int):
        return self.query_service.list_events(task_id)

    def list_children(self, task_id: int):
        return self.query_service.list_children(task_id)
