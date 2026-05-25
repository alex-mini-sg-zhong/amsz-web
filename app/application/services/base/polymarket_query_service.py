from __future__ import annotations

from datetime import datetime

from app.infrastructure.datasource.relational.models import (
    PolymarketEvent,
    PolymarketEventSnapshot,
    PolymarketSyncRun,
)
from app.infrastructure.repositories.polymarket_repository import PolymarketRepository


class PolymarketQueryService:
    def __init__(self, repository: PolymarketRepository) -> None:
        self.repository = repository

    def list_events(self, *, active: bool | None, limit: int) -> list[PolymarketEvent]:
        return self.repository.list_events(active=active, limit=limit)

    def get_event(self, event_id: str) -> PolymarketEvent | None:
        return self.repository.get_event(event_id)

    def list_snapshots(
        self,
        *,
        event_id: str,
        granularity: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
    ) -> list[PolymarketEventSnapshot]:
        return self.repository.list_snapshots(
            event_id=event_id,
            granularity=granularity,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
        )

    def get_sync_run(self, run_id: int) -> PolymarketSyncRun | None:
        return self.repository.get_sync_run(run_id)
