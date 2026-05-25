from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.application.services.base.polymarket_command_service import PolymarketCommandService
from app.application.services.base.polymarket_query_service import PolymarketQueryService
from app.contracts.http.polymarket import (
    PolymarketCatalogSyncRequest,
    PolymarketEventResponse,
    PolymarketEventSnapshotResponse,
    PolymarketSnapshotSyncRequest,
    PolymarketSyncRunResponse,
    PolymarketSyncTriggerResponse,
)
from app.interfaces.http.dependencies import (
    get_polymarket_command_service,
    get_polymarket_query_service,
    get_request_id,
    require_api_key,
)

router = APIRouter(
    prefix="/api/v1/integrations/polymarket",
    tags=["polymarket"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/events/catalog-sync", response_model=PolymarketSyncTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
def create_catalog_sync_task(
    payload: PolymarketCatalogSyncRequest,
    response: Response,
    request: Request,
    service: PolymarketCommandService = Depends(get_polymarket_command_service),
    request_id: str = Depends(get_request_id),
) -> PolymarketSyncTriggerResponse:
    task_id, task_status, created = service.create_catalog_sync_task(
        payload,
        request.headers.get("X-Client-Id"),
        request_id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return PolymarketSyncTriggerResponse(task_id=task_id, status=task_status, message="catalog sync accepted")


@router.post("/events/snapshot-sync", response_model=PolymarketSyncTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
def create_snapshot_sync_task(
    payload: PolymarketSnapshotSyncRequest,
    response: Response,
    request: Request,
    service: PolymarketCommandService = Depends(get_polymarket_command_service),
    request_id: str = Depends(get_request_id),
) -> PolymarketSyncTriggerResponse:
    task_id, task_status, created = service.create_snapshot_sync_task(
        payload,
        request.headers.get("X-Client-Id"),
        request_id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return PolymarketSyncTriggerResponse(task_id=task_id, status=task_status, message="snapshot sync accepted")


@router.get("/events", response_model=list[PolymarketEventResponse])
def list_polymarket_events(
    active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    service: PolymarketQueryService = Depends(get_polymarket_query_service),
) -> list[PolymarketEventResponse]:
    events = service.list_events(active=active, limit=limit)
    return [_to_event_response(event) for event in events]


@router.get("/events/{event_id}", response_model=PolymarketEventResponse)
def get_polymarket_event(
    event_id: str,
    service: PolymarketQueryService = Depends(get_polymarket_query_service),
) -> PolymarketEventResponse:
    event = service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Polymarket event not found")
    return _to_event_response(event)


@router.get("/events/{event_id}/snapshots", response_model=list[PolymarketEventSnapshotResponse])
def list_polymarket_event_snapshots(
    event_id: str,
    granularity: str | None = Query(default=None),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    service: PolymarketQueryService = Depends(get_polymarket_query_service),
) -> list[PolymarketEventSnapshotResponse]:
    snapshots = service.list_snapshots(
        event_id=event_id,
        granularity=granularity,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
    )
    return [
        PolymarketEventSnapshotResponse(
            snapshot_time=snapshot.snapshot_time,
            snapshot_granularity=snapshot.snapshot_granularity,
            active=snapshot.active,
            closed=snapshot.closed,
            archived=snapshot.archived,
            liquidity=snapshot.liquidity,
            volume=snapshot.volume,
            open_interest=snapshot.open_interest,
            volume_24hr=snapshot.volume_24hr,
            volume_1wk=snapshot.volume_1wk,
            volume_1mo=snapshot.volume_1mo,
            volume_1yr=snapshot.volume_1yr,
            comment_count=snapshot.comment_count,
            source_updated_at=snapshot.source_updated_at,
        )
        for snapshot in snapshots
    ]


@router.get("/sync-runs/{run_id}", response_model=PolymarketSyncRunResponse)
def get_polymarket_sync_run(
    run_id: int,
    service: PolymarketQueryService = Depends(get_polymarket_query_service),
) -> PolymarketSyncRunResponse:
    run = service.get_sync_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Polymarket sync run not found")
    return PolymarketSyncRunResponse(
        run_id=run.id,
        task_id=run.task_id,
        source=run.source,
        resource=run.resource,
        sync_type=run.sync_type,
        scope=run.scope,
        status=run.status,
        cursor_in=run.cursor_in,
        cursor_out=run.cursor_out,
        page_count=run.page_count,
        record_count=run.record_count,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _to_event_response(event) -> PolymarketEventResponse:
    return PolymarketEventResponse(
        polymarket_event_id=event.polymarket_event_id,
        slug=event.slug,
        title=event.title,
        category=event.category,
        subcategory=event.subcategory,
        active=event.active,
        closed=event.closed,
        archived=event.archived,
        featured=event.featured,
        liquidity=event.liquidity,
        volume=event.volume,
        open_interest=event.open_interest,
        volume_24hr=event.volume_24hr,
        volume_1wk=event.volume_1wk,
        volume_1mo=event.volume_1mo,
        volume_1yr=event.volume_1yr,
        comment_count=event.comment_count,
        source_created_at=event.source_created_at,
        source_updated_at=event.source_updated_at,
        last_snapshot_at=event.last_snapshot_at,
        synced_at=event.synced_at,
    )
