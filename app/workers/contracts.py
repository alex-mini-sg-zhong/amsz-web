from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable, Protocol

from app.domain.exceptions import NonRetryableTaskError


class TaskHandler(Protocol):
    def __call__(
        self,
        payload: dict[str, Any],
        context: "WorkerTaskContext",
    ) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class WorkerTaskContext:
    task_id: int
    task_type: str
    attempt_no: int
    worker_id: str
    parent_task_id: int | None
    _cancel_event: Event = field(repr=False)
    _progress_callback: Callable[[int, str | None], None] = field(repr=False)
    _cancel_check: Callable[[], bool] = field(repr=False)
    _child_result_loader: Callable[[int], list[dict[str, Any]]] = field(repr=False)

    def set_progress(self, progress: int, stage: str | None = None) -> None:
        self._progress_callback(progress, stage)

    def raise_if_canceled(self) -> None:
        if self._cancel_event.is_set() or self._cancel_check():
            raise NonRetryableTaskError("Task canceled", error_code="TASK_CANCELED")

    def load_child_results(self, parent_task_id: int) -> list[dict[str, Any]]:
        return self._child_result_loader(parent_task_id)
