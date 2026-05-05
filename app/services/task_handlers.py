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


@dataclass(slots=True)
class TaskContext:
    task_id: int
    task_type: str
    attempt_no: int
    worker_id: str
    cancel_event: Event
    progress_callback: Callable[[int, str | None], None]
    cancel_check: Callable[[], bool]

    def set_progress(self, progress: int, stage: str | None = None) -> None:
        self.progress_callback(progress, stage)

    def raise_if_canceled(self) -> None:
        if self.cancel_event.is_set() or self.cancel_check():
            raise NonRetryableTaskError("Task canceled", error_code="TASK_CANCELED")


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
        "app.services.task_handlers",
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


def build_handler_registry() -> dict[str, TaskHandler]:
    return {
        "noop.success": noop_success_handler,
        "sleep.echo": sleep_echo_handler,
        "force.retry": force_retry_handler,
    }
