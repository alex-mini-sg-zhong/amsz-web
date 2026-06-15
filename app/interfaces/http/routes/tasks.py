from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.application.services.aggregate.task_orchestration_service import (
    EXTERNAL_FANOUT_TASK_TYPE,
    INTERNAL_TASK_TYPES,
    TaskOrchestrationService,
)
from app.application.services.base.task_command_service import TaskCommandService
from app.application.services.base.task_query_service import TaskQueryService
from app.core.config import get_settings
from app.contracts.http.task import (
    TaskCancelResponse,
    TaskChildResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDetailResponse,
    TaskEventResponse,
    TaskListItemResponse,
    TaskRetryResponse,
)
from app.interfaces.http.dependencies import (
    get_request_id,
    get_task_command_service,
    get_task_orchestration_service,
    get_task_query_service,
    require_api_key,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_api_key)],
)
def create_task(
    payload: TaskCreateRequest,
    response: Response,
    request: Request,
    command_service: TaskCommandService = Depends(get_task_command_service),
    orchestration_service: TaskOrchestrationService = Depends(get_task_orchestration_service),
    request_id: str = Depends(get_request_id),
) -> TaskCreateResponse:
    created_by = request.headers.get("X-Client-Id")
    try:
        if payload.task_type in INTERNAL_TASK_TYPES:
            raise ValueError("Internal task types cannot be submitted directly")
        if payload.task_type == EXTERNAL_FANOUT_TASK_TYPE:
            task_id, task_status, created = orchestration_service.create_fanout_task(
                payload,
                created_by,
                request_id,
            )
        else:
            task_id, task_status, created = command_service.create_task(
                payload,
                created_by,
                request_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return TaskCreateResponse(
        task_id=task_id,
        status=task_status,
        message="task accepted" if created else "existing task returned",
    )


@router.get(
    "/{task_id}",
    response_model=TaskDetailResponse,
    dependencies=[Depends(require_api_key)],
)
def get_task(
    task_id: int,
    query_service: TaskQueryService = Depends(get_task_query_service),
) -> TaskDetailResponse:
    task = query_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskDetailResponse(
        task_id=task.id,
        task_type=task.task_type,
        queue_name=task.queue_name,
        task_role=task.task_role.value,
        parent_task_id=task.parent_task_id,
        status=task.status.value,
        progress=task.progress,
        current_stage=task.current_stage,
        attempt_no=task.attempt_no,
        max_attempts=task.max_attempts,
        error_code=task.error_code,
        error_message=task.error_message,
        result=task.result_json,
        total_children=task.total_children,
        succeeded_children=task.succeeded_children,
        failed_children=task.failed_children,
        running_children=task.running_children,
        child_summary=task.child_summary,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@router.get(
    "",
    response_model=list[TaskListItemResponse],
    dependencies=[Depends(require_api_key)],
)
def list_tasks(
    status_value: str | None = Query(default=None, alias="status"),
    task_type: str | None = None,
    queue_name: str | None = None,
    biz_key: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    query_service: TaskQueryService = Depends(get_task_query_service),
) -> list[TaskListItemResponse]:
    tasks = query_service.list_tasks(
        status=status_value,
        task_type=task_type,
        queue_name=queue_name,
        biz_key=biz_key,
        page=page,
        page_size=page_size,
    )
    return [
        TaskListItemResponse(
            task_id=task.id,
            task_type=task.task_type,
            queue_name=task.queue_name,
            task_role=task.task_role.value,
            status=task.status.value,
            progress=task.progress,
            created_at=task.created_at,
            finished_at=task.finished_at,
        )
        for task in tasks
    ]


@router.post(
    "/{task_id}/cancel",
    response_model=TaskCancelResponse,
    dependencies=[Depends(require_api_key)],
)
def cancel_task(
    task_id: int,
    command_service: TaskCommandService = Depends(get_task_command_service),
) -> TaskCancelResponse:
    task = command_service.request_cancel(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskCancelResponse(
        task_id=task.id,
        cancel_requested=task.cancel_requested,
        status=task.status.value,
    )


@router.post(
    "/{task_id}/retry",
    response_model=TaskRetryResponse,
    dependencies=[Depends(require_api_key)],
)
def retry_task(
    task_id: int,
    command_service: TaskCommandService = Depends(get_task_command_service),
) -> TaskRetryResponse:
    task = command_service.retry_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TaskRetryResponse(task_id=task.id, status=task.status.value, message="task rescheduled")


@router.get(
    "/{task_id}/events",
    response_model=list[TaskEventResponse],
    dependencies=[Depends(require_api_key)],
)
def list_task_events(
    task_id: int,
    query_service: TaskQueryService = Depends(get_task_query_service),
) -> list[TaskEventResponse]:
    task = query_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    settings = get_settings()
    if not settings.task_event_db_enabled:
        return []
    events = query_service.list_events(task_id)
    return [
        TaskEventResponse(
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            message=event.message,
            event_payload=event.event_payload,
            created_at=event.created_at,
        )
        for event in events
    ]


@router.get(
    "/{task_id}/children",
    response_model=list[TaskChildResponse],
    dependencies=[Depends(require_api_key)],
)
def list_task_children(
    task_id: int,
    query_service: TaskQueryService = Depends(get_task_query_service),
) -> list[TaskChildResponse]:
    task = query_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    children = query_service.list_children(task_id)
    return [
        TaskChildResponse(
            task_id=child.id,
            task_type=child.task_type,
            task_role=child.task_role.value,
            parent_task_id=child.parent_task_id,
            status=child.status.value,
            shard_index=child.shard_index,
            shard_key=child.shard_key,
            progress=child.progress,
            error_code=child.error_code,
            error_message=child.error_message,
            created_at=child.created_at,
            finished_at=child.finished_at,
        )
        for child in children
    ]
