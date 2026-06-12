from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.infrastructure.datasource.relational.models import SzdmItem, SzdmJob
from app.infrastructure.datasource.s3.client import S3ClientProvider
from app.infrastructure.repositories.szdm_repository import SzdmRepository


class SzdmQueryService:
    def __init__(self, repository: SzdmRepository) -> None:
        self.repository = repository

    def get_job(self, job_id: int) -> SzdmJob | None:
        job = self.repository.get_job(job_id)
        if job is not None:
            self.repository.refresh_job_counts(job.id)
        return job

    def get_report(self, job_id: int) -> tuple[SzdmJob | None, dict[str, Any] | None]:
        job = self.get_job(job_id)
        report_data: dict[str, Any] | None = None
        if job is not None and job.report_s3_key:
            settings = get_settings()
            s3 = S3ClientProvider(
                bucket=settings.szdm_s3_bucket,
                root_dir=settings.szdm_s3_root_dir,
            ).build()
            try:
                loaded = s3.get_json(job.report_s3_key)
                report_data = dict(loaded) if isinstance(loaded, dict) else {"value": loaded}
            except (OSError, ValueError):
                pass
        return job, report_data

    def list_items(
        self,
        *,
        job_id: int,
        status: str | None,
        reuse_status: str | None,
        item_key: str | None,
        condition_key: str | None,
        page: int,
        page_size: int,
    ) -> list[SzdmItem]:
        return self.repository.list_items(
            job_id=job_id,
            status=status,
            reuse_status=reuse_status,
            item_key=item_key,
            condition_key=condition_key,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
