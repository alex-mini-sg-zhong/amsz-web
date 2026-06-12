from __future__ import annotations

from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.repositories.szdm_repository import SzdmRepository
from app.infrastructure.runtime.worker_runner import WorkerRunner


def _create_job(client, *, items: list[dict], priority: int = 5, max_parallel_children: int = 2):
    response = client.post(
        "/api/v1/szdm/jobs",
        headers={"X-API-Key": "test-key", "X-Client-Id": "tester"},
        json={
            "priority": priority,
            "max_parallel_children": max_parallel_children,
            "dispatch_batch_size": max_parallel_children,
            "reuse_window_seconds": 86400,
            "items": items,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_szdm_job_executes_windowed_items_and_aggregates(client) -> None:
    created = _create_job(
        client,
        items=[
            {"item_key": "a", "condition_key": "c1", "payload": {}},
            {"item_key": "b", "condition_key": "c1", "payload": {}},
            {"item_key": "c", "condition_key": "c1", "payload": {}},
        ],
        max_parallel_children=2,
    )
    job_id = created["job_id"]

    detail = client.get(f"/api/v1/szdm/jobs/{job_id}", headers={"X-API-Key": "test-key"})
    assert detail.status_code == 200
    assert detail.json()["item_count"] == 3
    assert detail.json()["dispatched_count"] == 0

    runner = WorkerRunner(queue_name="default", concurrency=2)
    runner.run_once(wait_for_completion=True)

    first_items = client.get(f"/api/v1/szdm/jobs/{job_id}/items", headers={"X-API-Key": "test-key"})
    assert first_items.status_code == 200
    assert sum(1 for item in first_items.json() if item["status"] == "SUCCEEDED") == 2

    runner._last_scheduler_tick_at = None
    runner.run_once(wait_for_completion=True)
    runner._last_scheduler_tick_at = None
    runner.run_once(wait_for_completion=True)

    final_detail = client.get(f"/api/v1/szdm/jobs/{job_id}", headers={"X-API-Key": "test-key"})
    assert final_detail.status_code == 200
    assert final_detail.json()["status"] == "SUCCEEDED"
    assert final_detail.json()["succeeded_count"] == 3
    assert final_detail.json()["report_status"] == "SUCCEEDED"
    assert final_detail.json()["report_s3_key"].startswith("s3://")


def test_szdm_item_reuses_recent_s3_result(client) -> None:
    first = _create_job(
        client,
        items=[{"item_key": "reuse-key", "condition_key": "same", "payload": {}}],
    )
    runner = WorkerRunner(queue_name="default", concurrency=1)
    runner.run_once(wait_for_completion=True)

    second = _create_job(
        client,
        items=[{"item_key": "reuse-key", "condition_key": "same", "payload": {}}],
    )
    runner._last_scheduler_tick_at = None
    runner.run_once(wait_for_completion=True)

    items = client.get(
        f"/api/v1/szdm/jobs/{second['job_id']}/items",
        headers={"X-API-Key": "test-key"},
    )
    assert items.status_code == 200
    assert items.json()[0]["reuse_status"] == "REUSED"


def test_szdm_priority_update_affects_job_and_item(client) -> None:
    created = _create_job(
        client,
        items=[{"item_key": "p", "condition_key": "c", "payload": {}}],
        priority=1,
    )
    job_id = created["job_id"]
    items = client.get(f"/api/v1/szdm/jobs/{job_id}/items", headers={"X-API-Key": "test-key"})
    item_id = items.json()[0]["item_id"]

    job_priority = client.post(
        f"/api/v1/szdm/jobs/{job_id}/priority",
        headers={"X-API-Key": "test-key"},
        json={"priority": 9},
    )
    item_priority = client.post(
        f"/api/v1/szdm/jobs/{job_id}/items/{item_id}/priority",
        headers={"X-API-Key": "test-key"},
        json={"priority": 8},
    )

    assert job_priority.status_code == 200
    assert job_priority.json()["priority"] == 9
    assert item_priority.status_code == 200
    assert item_priority.json()["priority"] == 8
    with session_scope() as session:
        job = SzdmRepository(session).get_job(job_id)
        item = SzdmRepository(session).get_item(item_id)
        assert job is not None and job.priority == 9
        assert item is not None and item.priority == 8
