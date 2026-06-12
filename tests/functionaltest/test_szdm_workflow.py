from __future__ import annotations

from datetime import datetime

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


def _run_worker_until_job_status(client, job_id: int, target_status: str, max_iterations: int = 30) -> dict:
    runner = WorkerRunner(queue_name="default", concurrency=2)
    for iteration in range(max_iterations):
        detail = client.get(
            f"/api/v1/szdm/jobs/{job_id}", headers={"X-API-Key": "test-key"}
        )
        assert detail.status_code == 200
        current = detail.json()
        if current["status"] == target_status:
            return current
        if current["status"] == "FAILED":
            raise AssertionError(f"Job {job_id} reached FAILED status unexpectedly")
        runner._last_scheduler_tick_at = None
        runner.run_once(wait_for_completion=True)
    raise AssertionError(
        f"Job {job_id} did not reach {target_status} after {max_iterations} iterations"
    )


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


def test_szdm_large_job_50_items_calculates_average_execution_time(client) -> None:
    item_count = 50
    created = _create_job(
        client,
        items=[
            {"item_key": f"item-{i:03d}", "condition_key": "perf-test", "payload": {}}
            for i in range(item_count)
        ],
        max_parallel_children=item_count,
    )
    job_id = created["job_id"]

    _run_worker_until_job_status(client, job_id=job_id, target_status="SUCCEEDED")

    items_response = client.get(
        f"/api/v1/szdm/jobs/{job_id}/items",
        headers={"X-API-Key": "test-key"},
        params={"page_size": item_count},
    )
    assert items_response.status_code == 200
    items = items_response.json()
    assert len(items) == item_count

    succeeded_count = 0
    total_duration_seconds = 0.0
    durations: list[float] = []
    for item in items:
        assert item["status"] == "SUCCEEDED", f"Item {item['item_key']} should be SUCCEEDED"
        succeeded_count += 1
        started_at = item.get("started_at")
        finished_at = item.get("finished_at")
        assert started_at is not None, f"Item {item['item_key']} missing started_at"
        assert finished_at is not None, f"Item {item['item_key']} missing finished_at"
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at)
        duration = (finished - started).total_seconds()
        assert duration >= 0, f"Item {item['item_key']} has negative duration"
        durations.append(duration)
        total_duration_seconds += duration

    assert succeeded_count == item_count
    average_duration = total_duration_seconds / item_count
    min_duration = min(durations)
    max_duration = max(durations)

    job_detail = client.get(
        f"/api/v1/szdm/jobs/{job_id}", headers={"X-API-Key": "test-key"}
    )
    assert job_detail.status_code == 200
    job = job_detail.json()
    assert job["status"] == "SUCCEEDED"
    assert job["succeeded_count"] == item_count
    assert job["report_status"] == "SUCCEEDED"
    assert job["report_s3_key"].startswith("s3://")

    report_response = client.get(
        f"/api/v1/szdm/jobs/{job_id}/report", headers={"X-API-Key": "test-key"}
    )
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["report_data"] is not None
    assert "items" in report["report_data"]
    assert report["report_data"]["summary"]["item_count"] == item_count

    print(
        f"\n  50-item job stats: "
        f"avg={average_duration:.4f}s, "
        f"min={min_duration:.4f}s, "
        f"max={max_duration:.4f}s"
    )
    assert average_duration > 0, "Average execution time should be positive"
