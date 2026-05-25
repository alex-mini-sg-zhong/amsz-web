from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.app_logging import get_logger
from app.core.config import get_settings
from app.core.time import utc_now
from app.domain.exceptions import NonRetryableTaskError
from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.integrations.polymarket_client import PolymarketClient
from app.infrastructure.repositories.polymarket_repository import PolymarketRepository
from app.workers.contracts import WorkerTaskContext


class PolymarketSyncService:
    def __init__(self, client: PolymarketClient | None = None) -> None:
        self.settings = get_settings()
        self.client = client or PolymarketClient()
        self.logger = get_logger("app.application.services.aggregate.polymarket_sync")

    def run_catalog_sync(
        self,
        payload: dict[str, Any],
        context: WorkerTaskContext,
    ) -> dict[str, Any]:
        scope = str(payload.get("scope", "default"))
        limit = self._normalize_limit(payload.get("limit"), self.settings.polymarket_catalog_limit)
        closed = payload.get("closed")
        reset_cursor = bool(payload.get("reset_cursor", False))
        resource = "events.catalog"

        with session_scope() as session:
            repository = PolymarketRepository(session)
            state = repository.get_or_create_sync_state(resource=resource, scope=scope)
            cursor_in = payload.get("after_cursor") or (None if reset_cursor else state.active_cursor)
            run = repository.create_sync_run(
                task_id=context.task_id,
                source="polymarket",
                resource=resource,
                sync_type="catalog",
                scope=scope,
                cursor_in=cursor_in,
            )
            run_id = run.id

        cursor = cursor_in
        page_count = 0
        record_count = 0
        cursor_out = cursor_in
        latest_updated_at: datetime | None = None

        try:
            while True:
                response = self.client.list_events_keyset(
                    limit=limit,
                    after_cursor=cursor,
                    closed=closed,
                )
                events = list(response.get("events") or [])
                next_cursor = response.get("next_cursor")
                page_count += 1
                synced_at = utc_now()

                with session_scope() as session:
                    repository = PolymarketRepository(session)
                    for event_payload in events:
                        repository.upsert_event(event_payload, synced_at=synced_at)
                        repository.store_raw_event(event_payload, synced_at=synced_at)
                        latest_updated_at = self._max_datetime(
                            latest_updated_at,
                            repository.extract_source_updated_at(event_payload),
                        )

                record_count += len(events)
                context.set_progress(min(95, page_count * 10), "catalog_sync")

                if not next_cursor or next_cursor == cursor or not events:
                    cursor_out = next_cursor or cursor
                    break
                cursor = next_cursor
                cursor_out = cursor

            finished_at = utc_now()
            with session_scope() as session:
                repository = PolymarketRepository(session)
                repository.finish_sync_run(
                    run_id=run_id,
                    status="SUCCEEDED",
                    cursor_out=cursor_out,
                    page_count=page_count,
                    record_count=record_count,
                    error_message=None,
                    finished_at=finished_at,
                )
                repository.update_sync_state(
                    resource=resource,
                    scope=scope,
                    active_cursor=cursor_out,
                    last_success_at=finished_at,
                    last_event_updated_at=latest_updated_at,
                )
            context.set_progress(100, "catalog_complete")
            return {
                "sync_type": "catalog",
                "scope": scope,
                "page_count": page_count,
                "record_count": record_count,
                "cursor_out": cursor_out,
            }
        except Exception as exc:
            finished_at = utc_now()
            with session_scope() as session:
                repository = PolymarketRepository(session)
                repository.finish_sync_run(
                    run_id=run_id,
                    status="FAILED",
                    cursor_out=cursor_out,
                    page_count=page_count,
                    record_count=record_count,
                    error_message=str(exc),
                    finished_at=finished_at,
                )
            raise

    def run_snapshot_sync(
        self,
        payload: dict[str, Any],
        context: WorkerTaskContext,
    ) -> dict[str, Any]:
        scope = str(payload.get("scope", "hot"))
        granularity = str(payload.get("snapshot_granularity") or self._default_granularity(scope))
        limit = self._normalize_limit(payload.get("limit"), self.settings.polymarket_snapshot_limit)
        requested_event_ids = [str(value) for value in payload.get("event_ids") or []]
        resource = f"events.snapshot.{scope}"

        with session_scope() as session:
            repository = PolymarketRepository(session)
            run = repository.create_sync_run(
                task_id=context.task_id,
                source="polymarket",
                resource=resource,
                sync_type="snapshot",
                scope=scope,
                cursor_in=None,
            )
            run_id = run.id
            if requested_event_ids:
                event_ids = requested_event_ids
            else:
                event_ids = [
                    event.polymarket_event_id
                    for event in repository.list_events_for_snapshot(scope=scope, limit=limit)
                ]

        if not event_ids:
            finished_at = utc_now()
            with session_scope() as session:
                repository = PolymarketRepository(session)
                repository.finish_sync_run(
                    run_id=run_id,
                    status="SUCCEEDED",
                    cursor_out=None,
                    page_count=0,
                    record_count=0,
                    error_message=None,
                    finished_at=finished_at,
                )
                repository.update_sync_state(
                    resource=resource,
                    scope=scope,
                    active_cursor=None,
                    last_success_at=finished_at,
                    last_snapshot_at=finished_at,
                    last_event_updated_at=None,
                )
            return {
                "sync_type": "snapshot",
                "scope": scope,
                "record_count": 0,
                "page_count": 0,
                "snapshot_granularity": granularity,
            }

        page_count = 0
        record_count = 0
        latest_updated_at: datetime | None = None
        snapshot_time = self._bucket_snapshot_time(utc_now(), granularity)

        try:
            total = len(event_ids)
            for index, event_id in enumerate(event_ids, start=1):
                event_payload = self.client.get_event_by_id(event_id)
                synced_at = utc_now()
                with session_scope() as session:
                    repository = PolymarketRepository(session)
                    repository.upsert_event(event_payload, synced_at=synced_at)
                    repository.store_raw_event(event_payload, synced_at=synced_at)
                    repository.insert_snapshot(
                        event_payload,
                        snapshot_time=snapshot_time,
                        granularity=granularity,
                        run_id=run_id,
                    )
                    latest_updated_at = self._max_datetime(
                        latest_updated_at,
                        repository.extract_source_updated_at(event_payload),
                    )
                page_count += 1
                record_count += 1
                context.set_progress(int((index / total) * 100), "snapshot_sync")

            finished_at = utc_now()
            with session_scope() as session:
                repository = PolymarketRepository(session)
                repository.finish_sync_run(
                    run_id=run_id,
                    status="SUCCEEDED",
                    cursor_out=None,
                    page_count=page_count,
                    record_count=record_count,
                    error_message=None,
                    finished_at=finished_at,
                )
                repository.update_sync_state(
                    resource=resource,
                    scope=scope,
                    active_cursor=None,
                    last_success_at=finished_at,
                    last_snapshot_at=snapshot_time,
                    last_event_updated_at=latest_updated_at,
                )
            return {
                "sync_type": "snapshot",
                "scope": scope,
                "record_count": record_count,
                "page_count": page_count,
                "snapshot_granularity": granularity,
                "snapshot_time": snapshot_time.isoformat(),
            }
        except Exception as exc:
            finished_at = utc_now()
            with session_scope() as session:
                repository = PolymarketRepository(session)
                repository.finish_sync_run(
                    run_id=run_id,
                    status="FAILED",
                    cursor_out=None,
                    page_count=page_count,
                    record_count=record_count,
                    error_message=str(exc),
                    finished_at=finished_at,
                )
            raise

    @staticmethod
    def _normalize_limit(raw_value: Any, default_value: int) -> int:
        if raw_value is None:
            return default_value
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise NonRetryableTaskError(
                "Invalid Polymarket sync limit",
                error_code="POLYMARKET_INVALID_LIMIT",
            ) from exc
        if value < 1 or value > 500:
            raise NonRetryableTaskError(
                "Polymarket sync limit must be between 1 and 500",
                error_code="POLYMARKET_INVALID_LIMIT",
            )
        return value

    @staticmethod
    def _default_granularity(scope: str) -> str:
        if scope == "hot":
            return "5m"
        if scope == "warm":
            return "15m"
        if scope == "cold":
            return "1d"
        return "15m"

    @staticmethod
    def _bucket_snapshot_time(snapshot_time: datetime, granularity: str) -> datetime:
        if granularity == "1m":
            return snapshot_time.replace(second=0, microsecond=0)
        if granularity == "5m":
            minute = snapshot_time.minute - (snapshot_time.minute % 5)
            return snapshot_time.replace(minute=minute, second=0, microsecond=0)
        if granularity == "15m":
            minute = snapshot_time.minute - (snapshot_time.minute % 15)
            return snapshot_time.replace(minute=minute, second=0, microsecond=0)
        if granularity == "1h":
            return snapshot_time.replace(minute=0, second=0, microsecond=0)
        if granularity == "1d":
            return snapshot_time.replace(hour=0, minute=0, second=0, microsecond=0)
        raise NonRetryableTaskError(
            f"Unsupported snapshot granularity: {granularity}",
            error_code="POLYMARKET_INVALID_GRANULARITY",
        )

    @staticmethod
    def _max_datetime(current: datetime | None, candidate: datetime | None) -> datetime | None:
        if current is None:
            return candidate
        if candidate is None:
            return current
        return max(current, candidate)
