from __future__ import annotations

from app.infrastructure.repositories.szdm_repository import SzdmRepository
from app.infrastructure.repositories.task_repository import TaskRepository


class SzdmSchedulerService:
    def tick(
        self,
        *,
        szdm_repository: SzdmRepository,
        task_repository: TaskRepository,
        queue_name: str,
        max_attempts: int,
        timeout_seconds: int,
        max_jobs: int,
        per_job_limit: int,
    ) -> int:
        created_count = 0
        jobs = szdm_repository.claim_dispatchable_jobs(limit=max_jobs)
        for job in jobs:
            created_count += szdm_repository.dispatch_items_for_job(
                job=job,
                task_repository=task_repository,
                queue_name=queue_name,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                created_by="szdm-scheduler",
                per_job_limit=per_job_limit,
            )
            szdm_repository.schedule_aggregate_if_ready(
                job=job,
                task_repository=task_repository,
                queue_name=queue_name,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                created_by="szdm-scheduler",
            )
        return created_count
