from __future__ import annotations

from time import sleep
from typing import Any

from app.domain.exceptions import NonRetryableTaskError
from app.workers.contracts import TaskHandler, WorkerTaskContext


def batch_sleep_echo_shard_handler(
    payload: dict[str, Any],
    context: WorkerTaskContext,
) -> dict[str, Any]:
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise NonRetryableTaskError("Shard items are required", error_code="INVALID_SHARD")

    results: list[dict[str, Any]] = []
    total_items = len(items)
    for index, item in enumerate(items, start=1):
        context.raise_if_canceled()
        seconds = int(item.get("seconds", 0))
        if seconds < 0 or seconds > 7200:
            raise NonRetryableTaskError("Invalid duration", error_code="INVALID_DURATION")
        sleep(seconds)
        results.append(
            {
                "echo": item.get("echo"),
                "slept_seconds": seconds,
                "item_index": index - 1,
            }
        )
        progress = int((index / total_items) * 100)
        context.set_progress(progress, "shard_running")

    return {"items": results, "item_count": total_items}


def batch_sleep_echo_aggregate_handler(
    payload: dict[str, Any],
    context: WorkerTaskContext,
) -> dict[str, Any]:
    parent_task_id = int(payload["parent_task_id"])
    child_results = context.load_child_results(parent_task_id)
    ordered_results = sorted(child_results, key=lambda item: item["shard_index"] or 0)

    items: list[dict[str, Any]] = []
    for child_result in ordered_results:
        result_payload = child_result.get("result") or {}
        items.extend(result_payload.get("items", []))

    context.set_progress(100, "aggregated")
    return {
        "child_count": len(ordered_results),
        "total_items": len(items),
        "items": items,
    }


HANDLERS: dict[str, TaskHandler] = {
    "batch.sleep.echo.shard": batch_sleep_echo_shard_handler,
    "batch.sleep.echo.aggregate": batch_sleep_echo_aggregate_handler,
}
