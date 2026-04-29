from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.db.models import Task, TaskAttempt, TaskEvent
from app.domain.enums import AttemptStatus, TaskStatus


@dataclass(slots=True)
class ClaimedTask:
    id: int
    task_type: str
    queue_name: str
    payload: dict[str, Any]
    attempt_no: int
    max_attempts: int
    timeout_seconds: int


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_task(
        self,
        *,
        task_type: str,
        queue_name: str,
        biz_key: str | None,
        idempotency_key: str | None,
        priority: int,
        max_attempts: int,
        timeout_seconds: int,
        scheduled_at: datetime,
        payload: dict[str, Any],
        created_by: str | None,
    ) -> tuple[Task, bool]:
        if idempotency_key:
            existing = self.session.scalar(
                select(Task).where(
                    Task.task_type == task_type,
                    Task.idempotency_key == idempotency_key,
                )
            )
            if existing:
                return existing, False

        task = Task(
            task_type=task_type,
            queue_name=queue_name,
            biz_key=biz_key,
            idempotency_key=idempotency_key,
            status=TaskStatus.PENDING,
            priority=priority,
            payload_json=payload,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            scheduled_at=scheduled_at,
            created_by=created_by,
        )
        self.session.add(task)
        self.session.flush()
        self._add_event(
            task_id=task.id,
            event_type="CREATED",
            from_status=None,
            to_status=TaskStatus.PENDING.value,
            message="Task created",
        )
        return task, True

    def get_task(self, task_id: int) -> Task | None:
        return self.session.get(Task, task_id)

    def list_tasks(
        self,
        *,
        status: str | None,
        task_type: str | None,
        queue_name: str | None,
        biz_key: str | None,
        limit: int,
        offset: int,
    ) -> list[Task]:
        stmt: Select[tuple[Task]] = select(Task).order_by(Task.created_at.desc())
        if status:
            stmt = stmt.where(Task.status == status)
        if task_type:
            stmt = stmt.where(Task.task_type == task_type)
        if queue_name:
            stmt = stmt.where(Task.queue_name == queue_name)
        if biz_key:
            stmt = stmt.where(Task.biz_key == biz_key)
        stmt = stmt.limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def list_events(self, task_id: int) -> list[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at.asc())
        )
        return list(self.session.scalars(stmt))

    def request_cancel(self, task_id: int) -> Task | None:
        task = self.session.get(Task, task_id)
        if task is None:
            return None

        previous_status = task.status.value
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELED
            task.finished_at = utc_now()
            task.cancel_requested = True
            task.lease_owner = None
            task.lease_until = None
            self._add_event(
                task_id=task.id,
                event_type="CANCELED",
                from_status=previous_status,
                to_status=TaskStatus.CANCELED.value,
                message="Task canceled before execution",
            )
            return task

        if task.status == TaskStatus.RUNNING:
            task.cancel_requested = True
            self._add_event(
                task_id=task.id,
                event_type="CANCEL_REQUESTED",
                from_status=previous_status,
                to_status=previous_status,
                message="Cancel requested",
            )
            return task

        return task

    def retry_task(self, task_id: int) -> Task | None:
        task = self.session.get(Task, task_id)
        if task is None:
            return None

        if task.status not in {TaskStatus.FAILED, TaskStatus.DEAD, TaskStatus.CANCELED}:
            return task

        previous_status = task.status.value
        task.status = TaskStatus.PENDING
        task.error_code = None
        task.error_message = None
        task.progress = 0
        task.current_stage = None
        task.result_json = None
        task.cancel_requested = False
        task.finished_at = None
        task.lease_owner = None
        task.lease_until = None
        task.scheduled_at = utc_now()
        self._add_event(
            task_id=task.id,
            event_type="RETRIED",
            from_status=previous_status,
            to_status=TaskStatus.PENDING.value,
            message="Task manually retried",
        )
        return task

    def claim_tasks(
        self,
        *,
        queue_name: str,
        worker_id: str,
        pod_name: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[ClaimedTask]:
        now = utc_now()
        stmt = (
            select(Task)
            .where(
                Task.queue_name == queue_name,
                Task.status.in_([TaskStatus.PENDING, TaskStatus.RETRY_WAIT]),
                Task.scheduled_at <= now,
            )
            .order_by(Task.priority.desc(), Task.scheduled_at.asc(), Task.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        tasks = list(self.session.scalars(stmt))
        claimed: list[ClaimedTask] = []

        for task in tasks:
            previous_status = task.status.value
            task.status = TaskStatus.RUNNING
            task.lease_owner = worker_id
            task.lease_until = now + timedelta(seconds=lease_seconds)
            task.attempt_no += 1
            if task.started_at is None:
                task.started_at = now
            task.cancel_requested = False
            task.error_code = None
            task.error_message = None
            task.current_stage = "claimed"
            self.session.add(
                TaskAttempt(
                    task_id=task.id,
                    attempt_no=task.attempt_no,
                    worker_id=worker_id,
                    pod_name=pod_name,
                    status=AttemptStatus.RUNNING,
                )
            )
            self._add_event(
                task_id=task.id,
                event_type="CLAIMED",
                from_status=previous_status,
                to_status=TaskStatus.RUNNING.value,
                message="Task claimed by worker",
                payload={"worker_id": worker_id},
            )
            claimed.append(
                ClaimedTask(
                    id=task.id,
                    task_type=task.task_type,
                    queue_name=task.queue_name,
                    payload=task.payload_json,
                    attempt_no=task.attempt_no,
                    max_attempts=task.max_attempts,
                    timeout_seconds=task.timeout_seconds,
                )
            )
        return claimed

    def renew_lease(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        now = utc_now()
        task = self.session.get(Task, task_id)
        if task is None or task.status != TaskStatus.RUNNING or task.lease_owner != worker_id:
            return False

        task.lease_until = now + timedelta(seconds=lease_seconds)
        attempt = self.session.scalar(
            select(TaskAttempt).where(
                TaskAttempt.task_id == task_id,
                TaskAttempt.attempt_no == attempt_no,
            )
        )
        if attempt:
            attempt.last_heartbeat_at = now
        return True

    def is_cancel_requested(self, task_id: int) -> bool:
        task = self.session.get(Task, task_id)
        return bool(task and task.cancel_requested)

    def update_progress(
        self,
        *,
        task_id: int,
        worker_id: str,
        progress: int,
        current_stage: str | None,
    ) -> bool:
        task = self.session.get(Task, task_id)
        if task is None or task.status != TaskStatus.RUNNING or task.lease_owner != worker_id:
            return False
        task.progress = max(0, min(progress, 100))
        task.current_stage = current_stage
        return True

    def mark_succeeded(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        result: dict[str, Any] | None,
    ) -> None:
        task = self._get_running_owned_task(task_id=task_id, worker_id=worker_id)
        previous_status = task.status.value
        task.status = TaskStatus.SUCCEEDED
        task.result_json = result
        task.progress = 100
        task.current_stage = "completed"
        task.finished_at = utc_now()
        task.lease_owner = None
        task.lease_until = None
        self._update_attempt_status(task_id, attempt_no, AttemptStatus.SUCCEEDED)
        self._add_event(
            task_id=task.id,
            event_type="SUCCEEDED",
            from_status=previous_status,
            to_status=TaskStatus.SUCCEEDED.value,
            message="Task completed successfully",
        )

    def mark_retry_wait(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        error_code: str,
        error_message: str,
        scheduled_at: datetime,
    ) -> None:
        task = self._get_running_owned_task(task_id=task_id, worker_id=worker_id)
        previous_status = task.status.value
        task.status = TaskStatus.RETRY_WAIT
        task.error_code = error_code
        task.error_message = self._truncate(error_message)
        task.current_stage = "retry_wait"
        task.scheduled_at = scheduled_at
        task.lease_owner = None
        task.lease_until = None
        self._update_attempt_status(
            task_id,
            attempt_no,
            AttemptStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )
        self._add_event(
            task_id=task.id,
            event_type="RETRY_WAIT",
            from_status=previous_status,
            to_status=TaskStatus.RETRY_WAIT.value,
            message="Task scheduled for retry",
            payload={"scheduled_at": scheduled_at.isoformat()},
        )

    def mark_failed(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        error_code: str,
        error_message: str,
        attempt_status: AttemptStatus = AttemptStatus.FAILED,
    ) -> None:
        task = self._get_running_owned_task(task_id=task_id, worker_id=worker_id)
        previous_status = task.status.value
        task.status = TaskStatus.FAILED
        task.error_code = error_code
        task.error_message = self._truncate(error_message)
        task.current_stage = "failed"
        task.finished_at = utc_now()
        task.lease_owner = None
        task.lease_until = None
        self._update_attempt_status(
            task_id,
            attempt_no,
            attempt_status,
            error_code=error_code,
            error_message=error_message,
        )
        self._add_event(
            task_id=task.id,
            event_type="FAILED",
            from_status=previous_status,
            to_status=TaskStatus.FAILED.value,
            message="Task failed",
        )

    def mark_dead(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        task = self._get_running_owned_task(task_id=task_id, worker_id=worker_id)
        previous_status = task.status.value
        task.status = TaskStatus.DEAD
        task.error_code = error_code
        task.error_message = self._truncate(error_message)
        task.current_stage = "dead"
        task.finished_at = utc_now()
        task.lease_owner = None
        task.lease_until = None
        self._update_attempt_status(
            task_id,
            attempt_no,
            AttemptStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )
        self._add_event(
            task_id=task.id,
            event_type="DEAD",
            from_status=previous_status,
            to_status=TaskStatus.DEAD.value,
            message="Task exhausted retries",
        )

    def mark_canceled(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
    ) -> None:
        task = self._get_running_owned_task(task_id=task_id, worker_id=worker_id)
        previous_status = task.status.value
        task.status = TaskStatus.CANCELED
        task.current_stage = "canceled"
        task.finished_at = utc_now()
        task.lease_owner = None
        task.lease_until = None
        self._update_attempt_status(task_id, attempt_no, AttemptStatus.CANCELED)
        self._add_event(
            task_id=task.id,
            event_type="CANCELED",
            from_status=previous_status,
            to_status=TaskStatus.CANCELED.value,
            message="Task canceled during execution",
        )

    def recover_expired_running_tasks(self, limit: int) -> int:
        now = utc_now()
        stmt = (
            select(Task)
            .where(
                Task.status == TaskStatus.RUNNING,
                Task.lease_until.is_not(None),
                Task.lease_until < now,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        tasks = list(self.session.scalars(stmt))
        for task in tasks:
            previous_status = task.status.value
            task.status = TaskStatus.PENDING
            task.lease_owner = None
            task.lease_until = None
            task.current_stage = "recovered"
            self._add_event(
                task_id=task.id,
                event_type="LEASE_EXPIRED",
                from_status=previous_status,
                to_status=TaskStatus.PENDING.value,
                message="Expired lease recovered",
            )
        return len(tasks)

    def _get_running_owned_task(self, *, task_id: int, worker_id: str) -> Task:
        task = self.session.get(Task, task_id)
        if task is None or task.status != TaskStatus.RUNNING or task.lease_owner != worker_id:
            raise ValueError(f"Task {task_id} is not owned by worker {worker_id}")
        return task

    def _update_attempt_status(
        self,
        task_id: int,
        attempt_no: int,
        status: AttemptStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        attempt = self.session.scalar(
            select(TaskAttempt).where(
                TaskAttempt.task_id == task_id,
                TaskAttempt.attempt_no == attempt_no,
            )
        )
        if attempt is None:
            return
        attempt.status = status
        attempt.finished_at = utc_now()
        attempt.error_code = error_code
        attempt.error_message = self._truncate(error_message)

    def _add_event(
        self,
        *,
        task_id: int,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        message: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            TaskEvent(
                task_id=task_id,
                event_type=event_type,
                from_status=from_status,
                to_status=to_status,
                message=message,
                event_payload=payload,
            )
        )

    @staticmethod
    def _truncate(value: str | None) -> str | None:
        if value is None:
            return None
        return value[:512]
