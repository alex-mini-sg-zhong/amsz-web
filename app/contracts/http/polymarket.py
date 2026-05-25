from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PolymarketCatalogSyncRequest(BaseModel):
    scope: str = Field(default="default", max_length=32)
    limit: int = Field(default=200, ge=1, le=500)
    reset_cursor: bool = False
    closed: bool | None = None
    queue_name: str = Field(default="default", max_length=32)


class PolymarketSnapshotSyncRequest(BaseModel):
    scope: str = Field(default="hot", max_length=32)
    limit: int = Field(default=100, ge=1, le=500)
    snapshot_granularity: str | None = Field(default=None, max_length=16)
    event_ids: list[str] | None = None
    queue_name: str = Field(default="default", max_length=32)


class PolymarketSyncTriggerResponse(BaseModel):
    task_id: int
    status: str
    message: str


class PolymarketEventResponse(BaseModel):
    polymarket_event_id: str
    slug: str | None
    title: str | None
    category: str | None
    subcategory: str | None
    active: bool | None
    closed: bool | None
    archived: bool | None
    featured: bool | None
    liquidity: float | None
    volume: float | None
    open_interest: float | None
    volume_24hr: float | None
    volume_1wk: float | None
    volume_1mo: float | None
    volume_1yr: float | None
    comment_count: int | None
    source_created_at: datetime | None
    source_updated_at: datetime | None
    last_snapshot_at: datetime | None
    synced_at: datetime


class PolymarketEventSnapshotResponse(BaseModel):
    snapshot_time: datetime
    snapshot_granularity: str
    active: bool | None
    closed: bool | None
    archived: bool | None
    liquidity: float | None
    volume: float | None
    open_interest: float | None
    volume_24hr: float | None
    volume_1wk: float | None
    volume_1mo: float | None
    volume_1yr: float | None
    comment_count: int | None
    source_updated_at: datetime | None


class PolymarketSyncRunResponse(BaseModel):
    run_id: int
    task_id: int | None
    source: str
    resource: str
    sync_type: str
    scope: str | None
    status: str
    cursor_in: str | None
    cursor_out: str | None
    page_count: int
    record_count: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
