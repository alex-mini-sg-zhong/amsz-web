from __future__ import annotations

from typing import Any

from app.application.services.aggregate.polymarket_sync_service import PolymarketSyncService
from app.workers.contracts import TaskHandler, WorkerTaskContext


def build_polymarket_sync_service() -> PolymarketSyncService:
    return PolymarketSyncService()


def polymarket_catalog_sync_handler(
    payload: dict[str, Any],
    context: WorkerTaskContext,
) -> dict[str, Any]:
    return build_polymarket_sync_service().run_catalog_sync(payload, context)


def polymarket_snapshot_sync_handler(
    payload: dict[str, Any],
    context: WorkerTaskContext,
) -> dict[str, Any]:
    return build_polymarket_sync_service().run_snapshot_sync(payload, context)


HANDLERS: dict[str, TaskHandler] = {
    "polymarket.events.catalog_sync": polymarket_catalog_sync_handler,
    "polymarket.events.snapshot_sync": polymarket_snapshot_sync_handler,
}
