from __future__ import annotations

from app.core.time import utc_now
from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.integrations.polymarket_client import PolymarketClient
from app.infrastructure.repositories.polymarket_repository import PolymarketRepository
from app.infrastructure.repositories.system_schedule_repository import SystemScheduleRepository
from app.infrastructure.runtime.worker_runner import WorkerRunner


def _sample_event(
    *,
    event_id: str,
    slug: str,
    active: bool = True,
    closed: bool = False,
    archived: bool = False,
    featured: bool = False,
    volume: float = 1000.0,
    open_interest: float = 100.0,
    liquidity: float = 500.0,
    comment_count: int = 2,
    updated_at: str = "2026-05-25T10:00:00Z",
) -> dict[str, object]:
    return {
        "id": event_id,
        "slug": slug,
        "title": f"Event {event_id}",
        "description": "demo",
        "category": "Politics",
        "subcategory": "Elections",
        "active": active,
        "closed": closed,
        "archived": archived,
        "featured": featured,
        "restricted": False,
        "enableOrderBook": True,
        "negRisk": False,
        "liquidity": liquidity,
        "volume": volume,
        "openInterest": open_interest,
        "volume24hr": 25.0,
        "volume1wk": 75.0,
        "volume1mo": 125.0,
        "volume1yr": 225.0,
        "commentCount": comment_count,
        "createdAt": "2026-05-20T10:00:00Z",
        "updatedAt": updated_at,
    }


def test_manual_catalog_sync_and_event_query(client, monkeypatch) -> None:
    monkeypatch.setattr(
        PolymarketClient,
        "list_events_keyset",
        lambda self, **kwargs: {
            "events": [_sample_event(event_id="1001", slug="election-1001", featured=True)],
            "next_cursor": None,
        },
    )

    create_response = client.post(
        "/api/v1/integrations/polymarket/events/catalog-sync",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={"scope": "default", "limit": 100},
    )
    assert create_response.status_code == 202

    runner = WorkerRunner(queue_name="default", concurrency=1)
    claimed = runner.run_once(wait_for_completion=True)
    assert claimed == 1

    list_response = client.get(
        "/api/v1/integrations/polymarket/events",
        headers={"X-API-Key": "test-key"},
    )
    assert list_response.status_code == 200
    assert list_response.json()[0]["polymarket_event_id"] == "1001"

    detail_response = client.get(
        "/api/v1/integrations/polymarket/events/1001",
        headers={"X-API-Key": "test-key"},
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["slug"] == "election-1001"


def test_scheduled_snapshot_sync_creates_snapshot(client, monkeypatch) -> None:
    initial_event = _sample_event(event_id="2001", slug="race-2001", featured=True, volume=2000.0)
    updated_event = _sample_event(event_id="2001", slug="race-2001", featured=True, volume=2500.0, open_interest=150.0, updated_at="2026-05-25T10:05:00Z")

    with session_scope() as session:
        polymarket_repository = PolymarketRepository(session)
        polymarket_repository.upsert_event(initial_event, synced_at=utc_now())
        schedule_repository = SystemScheduleRepository(session)
        schedule_repository.create_schedule(
            schedule_key="polymarket.events.snapshot_sync.hot",
            task_type="polymarket.events.snapshot_sync",
            interval_seconds=300,
            next_run_at=utc_now(),
            payload_json={"scope": "hot", "limit": 10, "snapshot_granularity": "5m"},
            queue_name="default",
        )

    monkeypatch.setattr(PolymarketClient, "get_event_by_id", lambda self, event_id: updated_event)

    runner = WorkerRunner(queue_name="default", concurrency=1)
    claimed = runner.run_once(wait_for_completion=True)
    assert claimed == 1

    snapshots_response = client.get(
        "/api/v1/integrations/polymarket/events/2001/snapshots?granularity=5m",
        headers={"X-API-Key": "test-key"},
    )
    assert snapshots_response.status_code == 200
    assert len(snapshots_response.json()) == 1
    assert snapshots_response.json()[0]["volume"] == 2500.0

    with session_scope() as session:
        schedule = SystemScheduleRepository(session).get_schedule("polymarket.events.snapshot_sync.hot")
        assert schedule is not None
        assert schedule.last_task_id is not None
