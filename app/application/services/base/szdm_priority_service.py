from __future__ import annotations

from app.infrastructure.datasource.relational.models import SzdmItem, SzdmJob
from app.infrastructure.repositories.szdm_repository import SzdmRepository


class SzdmPriorityService:
    def __init__(self, repository: SzdmRepository) -> None:
        self.repository = repository

    def update_job_priority(self, *, job_id: int, priority: int) -> SzdmJob:
        return self.repository.update_job_priority(job_id=job_id, priority=priority)

    def update_item_priority(self, *, item_id: int, priority: int) -> SzdmItem:
        return self.repository.update_item_priority(item_id=item_id, priority=priority)
