from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import timedelta
from threading import Event, Thread
from time import sleep

from app.core.config import get_settings
from app.core.app_logging import get_logger
from app.core.time import utc_now
from app.db.session import session_scope
from app.domain.enums import AttemptStatus, TaskRole
from app.domain.exceptions import NonRetryableTaskError, RetryableTaskError, TaskError
from app.repositories.task_repository import ClaimedTask, TaskRepository
from app.services.task_handlers import TaskContext, TaskHandler, build_handler_registry

AGGREGATE_TASK_TYPE = "batch.sleep.echo.aggregate"


class WorkerRunner:
    def __init__(
        self,
        *,
        queue_name: str,
        concurrency: int,
        handler_registry: dict[str, TaskHandler] | None = None,
    ) -> None:
        self.settings = get_settings()
        self.worker_id = self.settings.worker_id
        self.logger = get_logger(
            "app.worker.runner",
            worker_id=self.worker_id,
        )
        self.queue_name = queue_name
        self.concurrency = concurrency
        self.handler_registry = handler_registry or build_handler_registry()
        self.executor = ThreadPoolExecutor(max_workers=self.concurrency)

    def run_forever(self) -> None:
        self.logger.info("Worker started")
        while True:
            self.run_once(wait_for_completion=False)
            sleep(self.settings.worker_poll_interval_seconds)

    def run_once(self, wait_for_completion: bool = True) -> int:
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

    def _run_claimed_task(self, task: ClaimedTask) -> None:
        logger = get_logger(
            "app.worker.runner",
            task_id=task.id,
            worker_id=self.worker_id,
        )
        handler = self.handler_registry.get(task.task_type)
        if handler is None:
            self._mark_failed(
                task=task,
                error_code="UNKNOWN_TASK_TYPE",
                error_message=f"Unknown task type: {task.task_type}",
            )
            return

        cancel_event = Event()
        heartbeat_stop = Event()
        heartbeat_thread = Thread(
            target=self._heartbeat_loop,
            args=(task, heartbeat_stop, cancel_event),
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            context = TaskContext(
                task_id=task.id,
                task_type=task.task_type,
                attempt_no=task.attempt_no,
                worker_id=self.worker_id,
                parent_task_id=task.parent_task_id,
                cancel_event=cancel_event,
                progress_callback=lambda progress, stage: self._update_progress(
                    task.id,
                    progress,
                    stage,
                ),
                cancel_check=lambda: self._is_cancel_requested(task.id, task.parent_task_id),
                child_result_loader=self._load_child_results,
            )
            result = handler(task.payload, context)
            aggregate_created_by: str | None = None
            with session_scope() as session:
                repository = TaskRepository(session)
                completed_task = repository.mark_succeeded(
                    task_id=task.id,
                    attempt_no=task.attempt_no,
                    worker_id=self.worker_id,
                    result=result,
                )
                aggregate_created_by = completed_task.created_by
            self._handle_post_success(
                task=task,
                result=result,
                aggregate_created_by=aggregate_created_by,
            )
            logger.info("Task succeeded")
        except RetryableTaskError as exc:
            next_run = utc_now() + self._compute_backoff(task.attempt_no)
            if task.attempt_no >= task.max_attempts:
                self._mark_dead(task, exc.error_code, exc.message)
            else:
                with session_scope() as session:
                    repository = TaskRepository(session)
                    repository.mark_retry_wait(
                        task_id=task.id,
                        attempt_no=task.attempt_no,
                        worker_id=self.worker_id,
                        error_code=exc.error_code,
                        error_message=exc.message,
                        scheduled_at=next_run,
                    )
                self._handle_post_child_update(task)
                logger.info("Task scheduled for retry")
        except NonRetryableTaskError as exc:
            if exc.error_code == "TASK_CANCELED":
                self._mark_canceled(task)
            else:
                self._mark_failed(task, exc.error_code, exc.message)
        except TaskError as exc:
            self._mark_failed(task, exc.error_code, exc.message)
        except Exception as exc:  # pragma: no cover - fallback safety
            self._mark_failed(task, "UNHANDLED_ERROR", str(exc))
        finally:
            heartbeat_stop.set()
            cancel_event.set()
            heartbeat_thread.join(timeout=1)

    def _heartbeat_loop(
        self,
        task: ClaimedTask,
        stop_event: Event,
        cancel_event: Event,
    ) -> None:
        while not stop_event.wait(self.settings.worker_heartbeat_interval_seconds):
            with session_scope() as session:
                repository = TaskRepository(session)
                renewed = repository.renew_lease(
                    task_id=task.id,
                    attempt_no=task.attempt_no,
                    worker_id=self.worker_id,
                    lease_seconds=self.settings.worker_lease_seconds,
                )
                if not renewed:
                    cancel_event.set()
                    return
                if repository.is_cancel_requested(task.id, task.parent_task_id):
                    cancel_event.set()

    def _update_progress(self, task_id: int, progress: int, stage: str | None) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.update_progress(
                task_id=task_id,
                worker_id=self.worker_id,
                progress=progress,
                current_stage=stage,
            )

    def _is_cancel_requested(self, task_id: int, parent_task_id: int | None) -> bool:
        with session_scope() as session:
            repository = TaskRepository(session)
            return repository.is_cancel_requested(task_id, parent_task_id)

    def _load_child_results(self, parent_task_id: int) -> list[dict[str, object]]:
        with session_scope() as session:
            repository = TaskRepository(session)
            return repository.load_child_results(parent_task_id)

    def _mark_failed(self, task: ClaimedTask, error_code: str, error_message: str) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_failed(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=self.worker_id,
                error_code=error_code,
                error_message=error_message,
                attempt_status=AttemptStatus.FAILED,
            )
        self._handle_post_failure(task, error_code, error_message)

    def _mark_dead(self, task: ClaimedTask, error_code: str, error_message: str) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_dead(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=self.worker_id,
                error_code=error_code,
                error_message=error_message,
            )
        self._handle_post_failure(task, error_code, error_message)

    def _mark_canceled(self, task: ClaimedTask) -> None:
        with session_scope() as session:
            repository = TaskRepository(session)
            repository.mark_canceled(
                task_id=task.id,
                attempt_no=task.attempt_no,
                worker_id=self.worker_id,
            )
        self._handle_post_child_update(task)

    def _handle_post_success(
        self,
        *,
        task: ClaimedTask,
        result: dict[str, object] | None,
        aggregate_created_by: str | None,
    ) -> None:
        if task.task_role == TaskRole.CHILD and task.parent_task_id is not None:
            self._handle_post_child_update(
                task,
                aggregate_created_by=aggregate_created_by,
            )
            return

        if task.task_role == TaskRole.AGGREGATE and task.parent_task_id is not None:
            with session_scope() as session:
                repository = TaskRepository(session)
                repository.mark_parent_succeeded(
                    parent_task_id=task.parent_task_id,
                    result=result,
                )

    def _handle_post_failure(
        self,
        task: ClaimedTask,
        error_code: str,
        error_message: str,
    ) -> None:
        if task.task_role == TaskRole.CHILD and task.parent_task_id is not None:
            self._handle_post_child_update(task)
            return

        if task.task_role == TaskRole.AGGREGATE and task.parent_task_id is not None:
            with session_scope() as session:
                repository = TaskRepository(session)
                repository.mark_parent_failed(
                    parent_task_id=task.parent_task_id,
                    error_code=error_code,
                    error_message=error_message,
                )

    def _handle_post_child_update(
        self,
        task: ClaimedTask,
        aggregate_created_by: str | None = None,
    ) -> None:
        if task.task_role == TaskRole.CHILD and task.parent_task_id is not None:
            with session_scope() as session:
                repository = TaskRepository(session)
                repository.refresh_parent_state(task.parent_task_id)
                if aggregate_created_by is not None:
                    repository.schedule_aggregate_task_if_ready(
                        parent_task_id=task.parent_task_id,
                        aggregate_task_type=AGGREGATE_TASK_TYPE,
                        queue_name=task.queue_name,
                        priority=task.priority,
                        max_attempts=task.max_attempts,
                        timeout_seconds=task.timeout_seconds,
                        created_by=aggregate_created_by,
                    )

    @staticmethod
    def _compute_backoff(attempt_no: int) -> timedelta:
        seconds = min(300, 2 ** max(attempt_no - 1, 0))
        return timedelta(seconds=seconds)
