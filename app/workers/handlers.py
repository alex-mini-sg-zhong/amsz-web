from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import sleep
from typing import Any, Callable, Protocol

from app.core.app_logging import get_logger
from app.domain.exceptions import NonRetryableTaskError, RetryableTaskError


class TaskHandler(Protocol):
    def __call__(self, payload: dict[str, Any], context: "TaskContext") -> dict[str, Any] | None:
        ...


@dataclass
class TaskContext:
    task_id: int
    task_type: str
    attempt_no: int
    worker_id: str
    parent_task_id: int | None
    cancel_event: Event
    progress_callback: Callable[[int, str | None], None]
    cancel_check: Callable[[], bool]
    child_result_loader: Callable[[int], list[dict[str, Any]]]

    def set_progress(self, progress: int, stage: str | None = None) -> None:
        self.progress_callback(progress, stage)

    def raise_if_canceled(self) -> None:
        if self.cancel_event.is_set() or self.cancel_check():
            raise NonRetryableTaskError("Task canceled", error_code="TASK_CANCELED")

    def load_child_results(self, parent_task_id: int) -> list[dict[str, Any]]:
        return self.child_result_loader(parent_task_id)


def noop_success_handler(
    payload: dict[str, Any],
    context: TaskContext,
) -> dict[str, Any]:
    context.set_progress(100, "completed")
    return {"accepted": True, "echo": payload.get("echo")}


def sleep_echo_handler(
    payload: dict[str, Any],
    context: TaskContext,
) -> dict[str, Any]:
    total_seconds = int(payload.get("seconds", 1))
    if total_seconds < 0 or total_seconds > 7200:
        raise NonRetryableTaskError("Invalid duration", error_code="INVALID_DURATION")

    logger = get_logger(
        "app.workers.handlers",
        task_id=context.task_id,
        worker_id=context.worker_id,
    )
    for step in range(total_seconds):
        context.raise_if_canceled()
        progress = int(((step + 1) / max(total_seconds, 1)) * 100)
        context.set_progress(progress, "sleeping")
        logger.info("Task step executed")
        sleep(1)

    return {"slept_seconds": total_seconds, "echo": payload.get("echo")}


def force_retry_handler(
    payload: dict[str, Any],
    context: TaskContext,
) -> dict[str, Any] | None:
    context.set_progress(10, "retrying")
    raise RetryableTaskError("Simulated retryable failure", error_code="SIMULATED_RETRY")


def batch_sleep_echo_shard_handler(
    payload: dict[str, Any],
    context: TaskContext,
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
    context: TaskContext,
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


def build_handler_registry() -> dict[str, TaskHandler]:
    return {
        "noop.success": noop_success_handler,
        "sleep.echo": sleep_echo_handler,
        "force.retry": force_retry_handler,
        "batch.sleep.echo.shard": batch_sleep_echo_shard_handler,
        "batch.sleep.echo.aggregate": batch_sleep_echo_aggregate_handler,
    }
