from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.infrastructure.datasource.relational.models import (
    PolymarketEvent,
    PolymarketEventRaw,
    PolymarketEventSnapshot,
    PolymarketSyncRun,
    PolymarketSyncState,
)


class PolymarketRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_sync_run(
        self,
        *,
        task_id: int | None,
        source: str,
        resource: str,
        sync_type: str,
        scope: str | None,
        cursor_in: str | None,
    ) -> PolymarketSyncRun:
        run = PolymarketSyncRun(
            task_id=task_id,
            source=source,
            resource=resource,
            sync_type=sync_type,
            scope=scope,
            status="RUNNING",
            cursor_in=cursor_in,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish_sync_run(
        self,
        *,
        run_id: int,
        status: str,
        cursor_out: str | None,
        page_count: int,
        record_count: int,
        error_message: str | None,
        finished_at: datetime,
    ) -> PolymarketSyncRun:
        run = self.session.get(PolymarketSyncRun, run_id)
        if run is None:
            raise ValueError(f"Polymarket sync run {run_id} not found")
        run.status = status
        run.cursor_out = cursor_out
        run.page_count = page_count
        run.record_count = record_count
        run.error_message = error_message[:512] if error_message else None
        run.finished_at = finished_at
        return run

    def get_sync_run(self, run_id: int) -> PolymarketSyncRun | None:
        return self.session.get(PolymarketSyncRun, run_id)

    def get_or_create_sync_state(self, *, resource: str, scope: str | None) -> PolymarketSyncState:
        stmt = select(PolymarketSyncState).where(
            PolymarketSyncState.source == "polymarket",
            PolymarketSyncState.resource == resource,
            PolymarketSyncState.scope == scope,
        )
        state = self.session.scalar(stmt)
        if state is None:
            state = PolymarketSyncState(
                source="polymarket",
                resource=resource,
                scope=scope,
            )
            self.session.add(state)
            self.session.flush()
        return state

    def update_sync_state(
        self,
        *,
        resource: str,
        scope: str | None,
        active_cursor: str | None,
        last_success_at: datetime | None,
        last_snapshot_at: datetime | None = None,
        last_event_updated_at: datetime | None = None,
    ) -> PolymarketSyncState:
        state = self.get_or_create_sync_state(resource=resource, scope=scope)
        state.active_cursor = active_cursor
        state.last_success_at = last_success_at
        state.last_snapshot_at = last_snapshot_at
        state.last_event_updated_at = last_event_updated_at
        return state

    def upsert_event(self, event_payload: dict[str, Any], *, synced_at: datetime) -> PolymarketEvent:
        event_id = str(event_payload["id"])
        event = self.get_event(event_id)
        if event is None:
            event = PolymarketEvent(polymarket_event_id=event_id)
            self.session.add(event)

        event.slug = self._clean_str(event_payload.get("slug"))
        event.title = self._clean_str(event_payload.get("title"))
        event.description = self._clean_str(event_payload.get("description"))
        event.category = self._clean_str(event_payload.get("category"))
        event.subcategory = self._clean_str(event_payload.get("subcategory"))
        event.active = self._to_bool(event_payload.get("active"))
        event.closed = self._to_bool(event_payload.get("closed"))
        event.archived = self._to_bool(event_payload.get("archived"))
        event.featured = self._to_bool(event_payload.get("featured"))
        event.restricted = self._to_bool(event_payload.get("restricted"))
        event.enable_order_book = self._to_bool(event_payload.get("enableOrderBook"))
        event.neg_risk = self._to_bool(event_payload.get("negRisk"))
        event.liquidity = self._to_float(event_payload.get("liquidity"))
        event.volume = self._to_float(event_payload.get("volume"))
        event.open_interest = self._to_float(event_payload.get("openInterest"))
        event.volume_24hr = self._to_float(event_payload.get("volume24hr"))
        event.volume_1wk = self._to_float(event_payload.get("volume1wk"))
        event.volume_1mo = self._to_float(event_payload.get("volume1mo"))
        event.volume_1yr = self._to_float(event_payload.get("volume1yr"))
        event.comment_count = self._to_int(event_payload.get("commentCount"))
        event.source_created_at = self._parse_datetime(event_payload.get("createdAt") or event_payload.get("creationDate"))
        event.source_updated_at = self.extract_source_updated_at(event_payload)
        event.synced_at = synced_at
        self.session.flush()
        return event

    def store_raw_event(self, event_payload: dict[str, Any], *, synced_at: datetime) -> PolymarketEventRaw:
        event_id = str(event_payload["id"])
        payload_json = json.dumps(event_payload, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        stmt = select(PolymarketEventRaw).where(
            PolymarketEventRaw.polymarket_event_id == event_id,
            PolymarketEventRaw.payload_hash == payload_hash,
        )
        existing = self.session.scalar(stmt)
        if existing is not None:
            return existing
        raw = PolymarketEventRaw(
            polymarket_event_id=event_id,
            source_updated_at=self.extract_source_updated_at(event_payload),
            payload_hash=payload_hash,
            payload_json=event_payload,
            synced_at=synced_at,
        )
        self.session.add(raw)
        self.session.flush()
        return raw

    def insert_snapshot(
        self,
        event_payload: dict[str, Any],
        *,
        snapshot_time: datetime,
        granularity: str,
        run_id: int | None,
    ) -> PolymarketEventSnapshot:
        event_id = str(event_payload["id"])
        stmt = select(PolymarketEventSnapshot).where(
            PolymarketEventSnapshot.polymarket_event_id == event_id,
            PolymarketEventSnapshot.snapshot_time == snapshot_time,
            PolymarketEventSnapshot.snapshot_granularity == granularity,
        )
        snapshot = self.session.scalar(stmt)
        if snapshot is None:
            snapshot = PolymarketEventSnapshot(
                polymarket_event_id=event_id,
                snapshot_time=snapshot_time,
                snapshot_granularity=granularity,
            )
            self.session.add(snapshot)

        snapshot.active = self._to_bool(event_payload.get("active"))
        snapshot.closed = self._to_bool(event_payload.get("closed"))
        snapshot.archived = self._to_bool(event_payload.get("archived"))
        snapshot.liquidity = self._to_float(event_payload.get("liquidity"))
        snapshot.volume = self._to_float(event_payload.get("volume"))
        snapshot.open_interest = self._to_float(event_payload.get("openInterest"))
        snapshot.volume_24hr = self._to_float(event_payload.get("volume24hr"))
        snapshot.volume_1wk = self._to_float(event_payload.get("volume1wk"))
        snapshot.volume_1mo = self._to_float(event_payload.get("volume1mo"))
        snapshot.volume_1yr = self._to_float(event_payload.get("volume1yr"))
        snapshot.comment_count = self._to_int(event_payload.get("commentCount"))
        snapshot.source_updated_at = self.extract_source_updated_at(event_payload)
        snapshot.run_id = run_id
        self.session.flush()

        event = self.get_event(event_id)
        if event is not None:
            event.last_snapshot_at = snapshot_time
        return snapshot

    def list_events(self, *, active: bool | None, limit: int) -> list[PolymarketEvent]:
        stmt = select(PolymarketEvent).order_by(PolymarketEvent.synced_at.desc())
        if active is not None:
            stmt = stmt.where(PolymarketEvent.active == active)
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_event(self, event_id: str) -> PolymarketEvent | None:
        stmt = select(PolymarketEvent).where(PolymarketEvent.polymarket_event_id == event_id)
        return self.session.scalar(stmt)

    def list_events_for_snapshot(self, *, scope: str, limit: int) -> list[PolymarketEvent]:
        stmt = select(PolymarketEvent)
        if scope == "hot":
            stmt = stmt.where(
                PolymarketEvent.active.is_(True),
                PolymarketEvent.closed.is_not(True),
            ).order_by(
                desc(PolymarketEvent.featured),
                desc(PolymarketEvent.volume),
                desc(PolymarketEvent.open_interest),
            )
        elif scope == "warm":
            stmt = stmt.where(
                PolymarketEvent.active.is_(True),
                PolymarketEvent.closed.is_not(True),
            ).order_by(desc(PolymarketEvent.volume), desc(PolymarketEvent.open_interest))
        elif scope == "cold":
            stmt = stmt.where(
                (PolymarketEvent.closed.is_(True)) | (PolymarketEvent.archived.is_(True))
            ).order_by(desc(PolymarketEvent.synced_at))
        else:
            stmt = stmt.order_by(desc(PolymarketEvent.synced_at))
        stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def list_snapshots(
        self,
        *,
        event_id: str,
        granularity: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
    ) -> list[PolymarketEventSnapshot]:
        stmt = select(PolymarketEventSnapshot).where(
            PolymarketEventSnapshot.polymarket_event_id == event_id
        )
        if granularity:
            stmt = stmt.where(PolymarketEventSnapshot.snapshot_granularity == granularity)
        if start_at:
            stmt = stmt.where(PolymarketEventSnapshot.snapshot_time >= start_at)
        if end_at:
            stmt = stmt.where(PolymarketEventSnapshot.snapshot_time <= end_at)
        stmt = stmt.order_by(PolymarketEventSnapshot.snapshot_time.asc()).limit(limit)
        return list(self.session.scalars(stmt))

    def extract_source_updated_at(self, event_payload: dict[str, Any]) -> datetime | None:
        return self._parse_datetime(event_payload.get("updatedAt"))

    @staticmethod
    def _clean_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _to_bool(value: Any) -> bool | None:
        if value is None:
            return None
        return bool(value)

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
