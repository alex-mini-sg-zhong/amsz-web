from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.application.services.aggregate.szdm_orchestration_service import SzdmOrchestrationService
from app.application.services.base.szdm_priority_service import SzdmPriorityService
from app.application.services.base.szdm_query_service import SzdmQueryService
from app.contracts.http.szdm import (
    SzdmItemResponse,
    SzdmJobCreateRequest,
    SzdmJobCreateResponse,
    SzdmJobResponse,
    SzdmPriorityRequest,
    SzdmPriorityResponse,
    SzdmReportResponse,
)
from app.interfaces.http.dependencies import (
    get_szdm_orchestration_service,
    get_szdm_priority_service,
    get_szdm_query_service,
    require_api_key,
)

router = APIRouter(prefix="/api/v1/szdm/jobs", tags=["szdm"], dependencies=[Depends(require_api_key)])


@router.post("", response_model=SzdmJobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_szdm_job(
    payload: SzdmJobCreateRequest,
    request: Request,
    service: SzdmOrchestrationService = Depends(get_szdm_orchestration_service),
) -> SzdmJobCreateResponse:
    try:
        job_id, task_id, job_status = service.create_job(
            request=payload,
            created_by=request.headers.get("X-Client-Id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SzdmJobCreateResponse(job_id=job_id, task_id=task_id, status=job_status)


@router.get("/{job_id}", response_model=SzdmJobResponse)
def get_szdm_job(
    job_id: int,
    service: SzdmQueryService = Depends(get_szdm_query_service),
) -> SzdmJobResponse:
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SZDM job not found")
    return _build_job_response(job)


@router.get("/{job_id}/items", response_model=list[SzdmItemResponse])
def list_szdm_items(
    job_id: int,
    status_value: str | None = Query(default=None, alias="status"),
    reuse_status: str | None = None,
    item_key: str | None = None,
    condition_key: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    service: SzdmQueryService = Depends(get_szdm_query_service),
) -> list[SzdmItemResponse]:
    items = service.list_items(
        job_id=job_id,
        status=status_value,
        reuse_status=reuse_status,
        item_key=item_key,
        condition_key=condition_key,
        page=page,
        page_size=page_size,
    )
    return [_build_item_response(item) for item in items]


@router.get("/{job_id}/report", response_model=SzdmReportResponse)
def get_szdm_report(
    job_id: int,
    service: SzdmQueryService = Depends(get_szdm_query_service),
) -> SzdmReportResponse:
    job, report_data = service.get_report(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SZDM job not found")
    base = _build_job_response(job)
    return SzdmReportResponse(**base.model_dump(), report_data=report_data)


@router.post("/{job_id}/priority", response_model=SzdmPriorityResponse)
def update_szdm_job_priority(
    job_id: int,
    payload: SzdmPriorityRequest,
    service: SzdmPriorityService = Depends(get_szdm_priority_service),
) -> SzdmPriorityResponse:
    try:
        job = service.update_job_priority(job_id=job_id, priority=payload.priority)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SzdmPriorityResponse(id=job.id, priority=job.priority, message="job priority updated")


@router.post("/{job_id}/items/{item_id}/priority", response_model=SzdmPriorityResponse)
def update_szdm_item_priority(
    job_id: int,
    item_id: int,
    payload: SzdmPriorityRequest,
    query_service: SzdmQueryService = Depends(get_szdm_query_service),
    priority_service: SzdmPriorityService = Depends(get_szdm_priority_service),
) -> SzdmPriorityResponse:
    job = query_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SZDM job not found")
    try:
        item = priority_service.update_item_priority(item_id=item_id, priority=payload.priority)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if item.job_id != job_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SZDM item not found")
    return SzdmPriorityResponse(id=item.id, priority=item.priority, message="item priority updated")


def _build_job_response(job) -> SzdmJobResponse:
    progress = int((job.succeeded_count + job.failed_count) / max(job.item_count, 1) * 100)
    return SzdmJobResponse(
        job_id=job.id,
        parent_task_id=job.parent_task_id,
        status=job.status,
        priority=job.priority,
        item_count=job.item_count,
        dispatched_count=job.dispatched_count,
        running_count=job.running_count,
        succeeded_count=job.succeeded_count,
        failed_count=job.failed_count,
        reused_count=job.reused_count,
        generated_count=job.generated_count,
        progress=progress,
        input_s3_key=job.input_s3_key,
        report_status=job.report_status,
        report_s3_key=job.report_s3_key,
        report_summary=job.report_summary_json,
        created_at=job.created_at,
        updated_at=job.updated_at,
        finished_at=job.finished_at,
    )


def _build_item_response(item) -> SzdmItemResponse:
    return SzdmItemResponse(
        item_id=item.id,
        item_index=item.item_index,
        item_key=item.item_key,
        condition_key=item.condition_key,
        status=item.status,
        reuse_status=item.reuse_status,
        priority=item.priority,
        child_task_id=item.child_task_id,
        result_s3_key=item.result_s3_key,
        metrics=item.metrics_json,
        display_summary=item.display_summary_json,
        error_code=item.error_code,
        error_message=item.error_message,
        started_at=item.started_at,
        finished_at=item.finished_at,
    )
