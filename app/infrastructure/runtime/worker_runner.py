from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from threading import Event, Thread
from time import sleep

from app.application.services.aggregate.polymarket_sync_service import PolymarketSyncService
from app.application.services.aggregate.system_scheduler_service import SystemSchedulerService
from app.application.services.aggregate.szdm_scheduler_service import SzdmSchedulerService
from app.application.services.aggregate.task_execution_service import TaskExecutionService
from app.core.app_logging import get_logger
from app.core.config import get_settings
from app.core.time import utc_now
from app.domain.exceptions import NonRetryableTaskError, RetryableTaskError, TaskError
from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.repositories.system_schedule_repository import SystemScheduleRepository
from app.infrastructure.repositories.szdm_repository import SzdmRepository
from app.infrastructure.repositories.task_repository import ClaimedTask, TaskRepository
from app.workers.contracts import TaskHandler, WorkerTaskContext
from app.workers.registry import build_handler_registry


class WorkerRunner:
    def __init__(
        self,
        *,
        queue_name: str,
        concurrency: int,
        handler_registry: dict[str, TaskHandler] | None = None,
        worker_profile: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self.worker_id = self.settings.worker_id
        self.logger = get_logger("app.infrastructure.runtime.worker_runner", worker_id=self.worker_id)
        self.queue_name = queue_name
        self.concurrency = concurrency
        self.worker_profile = worker_profile or self.settings.worker_profile
        self.handler_registry = handler_registry or build_handler_registry(self.worker_profile)
        self.execution_service = TaskExecutionService()
        self.scheduler_service = SystemSchedulerService()
        self.szdm_scheduler_service = SzdmSchedulerService()
        self.executor = ThreadPoolExecutor(max_workers=self.concurrency)
        self._last_scheduler_tick_at: datetime | None = None

    def run_forever(self) -> None:
        self.logger.info(f"Worker started profile={self.worker_profile}")
        while True:
            self.run_once(wait_for_completion=False)
            sleep(self.settings.worker_poll_interval_seconds)

    def run_once(self, wait_for_completion: bool = True) -> int:
        self._run_scheduler_tick_if_due()

        with session_scope() as session:
            repository = TaskRepository(session)
            repository.recover_expired_running_tasks(self.settings.worker_recover_limit)
            claimed = repository.claim_tasks(
                queue_name=self.queue_name,
                worker_id=self.worker_id,
                pod_name=self.settings.pod_name,
                batch_size=self.settings.worker_claim_batch_size,
                lease_seconds=self.settings.worker_lease_seconds,
            )

        if not claimed:
            return 0

        futures: list[Future[None]] = []
        for task in claimed:
            futures.append(self.executor.submit(self._run_claimed_task, task))
        if wait_for_completion:
            wait(futures)
        return len(claimed)

    def _run_scheduler_tick_if_due(self) -> None:
        if not self.settings.scheduler_enabled:
            return
        now = utc_now()
        if self._last_scheduler_tick_at is not None:
            elapsed = (now - self._last_scheduler_tick_at).total_seconds()
            if elapsed < self.settings.scheduler_tick_interval_seconds:
                return
        self._last_scheduler_tick_at = now
        try:
            with session_scope() as session:
                task_repository = TaskRepository(session)
                created_count = self.scheduler_service.tick(
                    schedule_repository=SystemScheduleRepository(session),
                    task_repository=task_repository,
                    max_due_schedules=self.settings.scheduler_max_due_schedules,
                )
                created_count += self.szdm_scheduler_service.tick(
                    szdm_repository=SzdmRepository(session),
                    task_repository=task_repository,
                    queue_name=self.settings.szdm_queue_name,
                    max_attempts=self.settings.szdm_subtask_max_attempts,
                    timeout_seconds=self.settings.szdm_subtask_timeout_seconds,
                    max_jobs=self.settings.szdm_scheduler_max_jobs,
                    per_job_limit=self.settings.szdm_scheduler_per_job_dispatch_limit,
                )
            if created_count:
                self.logger.info(f"Scheduler created tasks count={created_count}")
        except Exception as exc:  # pragma: no cover - safety path
            self.logger.error(f"Scheduler tick failed error={exc}")

    def _run_claimed_task(self, task: ClaimedTask) -> None:
        logger = get_logger("app.infrastructure.runtime.worker_runner", task_id=task.id, worker_id=self.worker_id)
        handler = self.handler_registry.get(task.task_type)
        if handler is None:
            self._mark_failed(task=task, error_code="UNKNOWN_TASK_TYPE", error_message=f"Unknown task type: {task.task_type}")
            return

        cancel_event = Event()
        heartbeat_stop = Event()
        heartbeat_thread = Thread(target=self._heartbeat_loop, args=(task, heartbeat_stop, cancel_event), daemon=True)
        heartbeat_thread.start()

        try:
            context = WorkerTaskContext(
                task_id=task.id,
                task_type=task.task_type,
                attempt_no=task.attempt_no,
                worker_id=self.worker_id,
                parent_task_id=task.parent_task_id,
                _cancel_event=cancel_event,
                _progress_callback=lambda progress, stage: self._update_progress(task.id, progress, stage),
                _cancel_check=lambda: self._is_cancel_requested(task.id, task.parent_task_id),
                _child_result_loader=self._load_child_results,
            )
            result = handler(task.payload, context)
            self.execution_service.mark_task_succeeded(task=task, worker_id=self.worker_id, result=result)
            logger.info("Task succeeded")
        except RetryableTaskError as exc:
            next_run = utc_now() + self._compute_backoff(task.attempt_no)
            if task.attempt_no >= task.max_attempts:
                self._mark_dead(task, exc.error_code, exc.message)
            else:
                self.execution_service.mark_task_retry_wait(task=task, worker_id=self.worker_id, error_code=exc.error_code, error_message=exc.message, scheduled_at=next_run)
                logger.info("Task scheduled for retry")
        except NonRetryableTaskError as exc:
            if exc.error_code == "TASK_CANCELED":
                self._mark_canceled(task)
            else:
                self._mark_failed(task, exc.error_code, exc.message)
        except TaskError as exc:
            self._mark_failed(task, exc.error_code, exc.message)
        except Exception as exc:  # pragma: no cover
            self._mark_failed(task, "UNHANDLED_ERROR", str(exc))
        finally:
            heartbeat_stop.set()
            cancel_event.set()
            heartbeat_thread.join(timeout=1)

    def _heartbeat_loop(self, task: ClaimedTask, stop_event: Event, cancel_event: Event) -> None:
        while not stop_event.wait(self.settings.worker_heartbeat_interval_seconds):
            with session_scope() as session:
                repository = TaskRepository(session)
                renewed = repository.renew_lease(task_id=task.id, attempt_no=task.attempt_no, worker_id=self.worker_id, lease_seconds=self.settings.worker_lease_seconds)
                if not renewed:
                    cancel_event.set()
                    return
                if repository.is_cancel_requested(task.id, task.parent_task_id):
                    cancel_event.set()

    def _update_progress(self, task_id: int, progress: int, stage: str | None) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.update_progress(task_id=task_id, worker_id=self.worker_id, progress=progress, current_stage=stage)

    def _is_cancel_requested(self, task_id: int, parent_task_id: int | None) -> bool:
        return self.execution_service.is_cancel_requested(task_id, parent_task_id)

    def _load_child_results(self, parent_task_id: int) -> list[dict[str, object]]:
        return self.execution_service.load_child_results(parent_task_id)

    def _mark_failed(self, task: ClaimedTask, error_code: str, error_message: str) -> None:
        self.execution_service.mark_task_failed(task=task, worker_id=self.worker_id, error_code=error_code, error_message=error_message)

    def _mark_dead(self, task: ClaimedTask, error_code: str, error_message: str) -> None:
        self.execution_service.mark_task_dead(task=task, worker_id=self.worker_id, error_code=error_code, error_message=error_message)

    def _mark_canceled(self, task: ClaimedTask) -> None:
        self.execution_service.mark_task_canceled(task=task, worker_id=self.worker_id)

    @staticmethod
    def _compute_backoff(attempt_no: int) -> timedelta:
        seconds = min(300, 2 ** max(attempt_no - 1, 0))
        return timedelta(seconds=seconds)
