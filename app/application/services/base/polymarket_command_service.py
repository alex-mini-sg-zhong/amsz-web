from __future__ import annotations

from app.contracts.http.polymarket import (
    PolymarketCatalogSyncRequest,
    PolymarketSnapshotSyncRequest,
)
from app.core.app_logging import get_logger
from app.core.config import get_settings
from app.core.time import utc_now
from app.infrastructure.repositories.task_repository import TaskRepository

CATALOG_SYNC_TASK_TYPE = "polymarket.events.catalog_sync"
SNAPSHOT_SYNC_TASK_TYPE = "polymarket.events.snapshot_sync"


class PolymarketCommandService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository
        self.settings = get_settings()
        self.logger = get_logger("app.application.services.base.polymarket_command")

    def create_catalog_sync_task(
        self,
        request: PolymarketCatalogSyncRequest,
        created_by: str | None,
        request_id: str,
    ) -> tuple[int, str, bool]:
        payload = request.model_dump(exclude_none=True)
        task, created = self.repository.create_task(
            task_type=CATALOG_SYNC_TASK_TYPE,
            queue_name=request.queue_name or self.settings.worker_queue,
            biz_key=f"polymarket:catalog:{request.scope}",
            idempotency_key=f"catalog:{request.scope}:{request_id}",
            priority=6,
            max_attempts=3,
            timeout_seconds=7200,
            scheduled_at=utc_now(),
            payload=payload,
            created_by=created_by,
        )
        self.logger.info(
            "Created Polymarket catalog sync task",
            extra={"request_id": request_id, "task_id": task.id, "worker_id": "-"},
        )
        return task.id, task.status.value, created

    def create_snapshot_sync_task(
        self,
        request: PolymarketSnapshotSyncRequest,
        created_by: str | None,
        request_id: str,
    ) -> tuple[int, str, bool]:
        payload = request.model_dump(exclude_none=True)
        task, created = self.repository.create_task(
            task_type=SNAPSHOT_SYNC_TASK_TYPE,
            queue_name=request.queue_name or self.settings.worker_queue,
            biz_key=f"polymarket:snapshot:{request.scope}",
            idempotency_key=f"snapshot:{request.scope}:{request_id}",
            priority=6,
            max_attempts=3,
            timeout_seconds=7200,
            scheduled_at=utc_now(),
            payload=payload,
            created_by=created_by,
        )
        self.logger.info(
            "Created Polymarket snapshot sync task",
            extra={"request_id": request_id, "task_id": task.id, "worker_id": "-"},
        )
        return task.id, task.status.value, created
