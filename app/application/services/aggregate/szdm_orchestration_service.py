from __future__ import annotations

from datetime import datetime

from app.contracts.http.szdm import SzdmJobCreateRequest
from app.core.config import get_settings
from app.core.time import utc_now
from app.domain.enums import TaskRole, TaskStatus
from app.infrastructure.datasource.s3.client import S3ClientProvider
from app.infrastructure.repositories.szdm_repository import SzdmRepository
from app.infrastructure.repositories.task_repository import TaskRepository


class SzdmOrchestrationService:
    def __init__(self, task_repository: TaskRepository, szdm_repository: SzdmRepository) -> None:
        self.task_repository = task_repository
        self.szdm_repository = szdm_repository
        self.settings = get_settings()

    def create_job(
        self,
        *,
        request: SzdmJobCreateRequest,
        created_by: str | None,
    ) -> tuple[int, int, str]:
        if request.dispatch_batch_size > request.max_parallel_children:
            raise ValueError("dispatch_batch_size cannot exceed max_parallel_children")

        now = utc_now()
        parent_task, _ = self.task_repository.create_task(
            task_type="szdm",
            queue_name=self.settings.szdm_queue_name,
            biz_key=None,
            idempotency_key=None,
            priority=request.priority,
            max_attempts=1,
            timeout_seconds=self.settings.szdm_subtask_timeout_seconds,
            scheduled_at=now,
            payload={"status": "managed_by_szdm_job"},
            created_by=created_by,
            status=TaskStatus.PARTIALLY_RUNNING,
            task_role=TaskRole.PARENT,
            total_children=len(request.items),
            child_summary={},
        )
        timestamp = self._format_timestamp(now)
        job_s3_prefix = f"szdm/jobs/{parent_task.id}/{timestamp}"
        input_s3_key = f"{job_s3_prefix}/input.json"
        s3 = S3ClientProvider(
            provider=self.settings.szdm_s3_provider,
            bucket=self.settings.szdm_s3_bucket,
            root_dir=self.settings.szdm_s3_root_dir,
            region=self.settings.szdm_s3_region,
            endpoint_url=self.settings.szdm_s3_endpoint_url,
        ).build()
        input_s3_uri = s3.put_json(
            input_s3_key,
            {
                "items": [item.model_dump() for item in request.items],
                "report_options": request.report_options,
                "created_at": now.isoformat(),
            },
        )
        job = self.szdm_repository.create_job(
            parent_task_id=parent_task.id,
            job_s3_prefix=s3.to_uri(job_s3_prefix),
            input_s3_key=input_s3_uri,
            item_count=len(request.items),
            priority=request.priority,
            max_parallel_children=request.max_parallel_children,
            dispatch_batch_size=request.dispatch_batch_size,
            reuse_window_seconds=request.reuse_window_seconds,
        )
        parent_task.payload_json = {"job_id": job.id}
        self.szdm_repository.create_items(
            job_id=job.id,
            items=[item.model_dump() for item in request.items],
            priority=request.priority,
        )
        return job.id, parent_task.id, job.status

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.strftime("%Y%m%dT%H%M%S%f")
