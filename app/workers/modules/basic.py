from __future__ import annotations

from time import sleep
from typing import Any

from app.core.app_logging import get_logger
from app.domain.exceptions import NonRetryableTaskError, RetryableTaskError
from app.workers.contracts import TaskHandler, WorkerTaskContext


def noop_success_handler(
    payload: dict[str, Any],
    context: WorkerTaskContext,
) -> dict[str, Any]:
    context.set_progress(100, "completed")
    return {"accepted": True, "echo": payload.get("echo")}


def sleep_echo_handler(
    payload: dict[str, Any],
    context: WorkerTaskContext,
) -> dict[str, Any]:
    total_seconds = int(payload.get("seconds", 1))
    if total_seconds < 0 or total_seconds > 7200:
        raise NonRetryableTaskError("Invalid duration", error_code="INVALID_DURATION")

    logger = get_logger(
        "app.workers.modules.basic",
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
    context: WorkerTaskContext,
) -> dict[str, Any] | None:
    context.set_progress(10, "retrying")
    raise RetryableTaskError("Simulated retryable failure", error_code="SIMULATED_RETRY")


HANDLERS: dict[str, TaskHandler] = {
    "noop.success": noop_success_handler,
    "sleep.echo": sleep_echo_handler,
    "force.retry": force_retry_handler,
}
