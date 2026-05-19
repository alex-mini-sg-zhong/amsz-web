from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.db.models import Task, TaskAttempt, TaskEvent
from app.domain.enums import AttemptStatus, TaskRole, TaskStatus


@dataclass
class ClaimedTask:
    id: int
    task_type: str
    task_role: TaskRole
    queue_name: str
    priority: int
    payload: dict[str, Any]
    attempt_no: int
    max_attempts: int
    timeout_seconds: int
    parent_task_id: int | None
    shard_index: int | None


@dataclass
class ChildTaskSpec:
    task_type: str
    payload: dict[str, Any]
    shard_index: int
    shard_key: str
    priority: int


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
        status: TaskStatus = TaskStatus.PENDING,
        task_role: TaskRole = TaskRole.STANDALONE,
        parent_task_id: int | None = None,
        shard_index: int | None = None,
        shard_key: str | None = None,
        total_children: int = 0,
        succeeded_children: int = 0,
        failed_children: int = 0,
        running_children: int = 0,
        child_summary: dict[str, Any] | None = None,
        aggregation_dispatched: bool = False,
    ) -> tuple[Task, bool]:
        if idempotency_key and parent_task_id is None:
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
            task_role=task_role,
            parent_task_id=parent_task_id,
            biz_key=biz_key,
            idempotency_key=idempotency_key,
            shard_index=shard_index,
            shard_key=shard_key,
            status=status,
            priority=priority,
            payload_json=payload,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            scheduled_at=scheduled_at,
            created_by=created_by,
            total_children=total_children,
            succeeded_children=succeeded_children,
            failed_children=failed_children,
            running_children=running_children,
            child_summary=child_summary,
            aggregation_dispatched=aggregation_dispatched,
        )
        self.session.add(task)
        self.session.flush()
        self._add_event(
            task_id=task.id,
            event_type="CREATED",
            from_status=None,
            to_status=task.status.value,
            message="Task created",
            payload={
                "task_role": task.task_role.value,
                "parent_task_id": task.parent_task_id,
            },
        )
        return task, True

    def create_child_tasks(
        self,
        *,
        parent_task_id: int,
        queue_name: str,
        child_specs: list[ChildTaskSpec],
        max_attempts: int,
        timeout_seconds: int,
        created_by: str | None,
    ) -> list[Task]:
        tasks: list[Task] = []
        for child_spec in child_specs:
            task, _ = self.create_task(
                task_type=child_spec.task_type,
                queue_name=queue_name,
                biz_key=None,
                idempotency_key=None,
                priority=child_spec.priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                scheduled_at=utc_now(),
                payload=child_spec.payload,
                created_by=created_by,
                task_role=TaskRole.CHILD,
                parent_task_id=parent_task_id,
                shard_index=child_spec.shard_index,
                shard_key=child_spec.shard_key,
            )
            tasks.append(task)
        return tasks

    def transition_parent_to_running(self, parent_task_id: int, total_children: int) -> Task:
        parent = self._get_parent_task_for_update(parent_task_id)
        previous_status = parent.status.value
        parent.status = TaskStatus.PARTIALLY_RUNNING
        parent.current_stage = "children_running"
        parent.total_children = total_children
        parent.succeeded_children = 0
        parent.failed_children = 0
        parent.running_children = 0
        parent.child_summary = {
            "pending": total_children,
            "running": 0,
            "succeeded": 0,
            "failed": 0,
            "retry_wait": 0,
            "canceled": 0,
            "dead": 0,
        }
        self._add_event(
            task_id=parent.id,
            event_type="DISPATCHED",
            from_status=previous_status,
            to_status=TaskStatus.PARTIALLY_RUNNING.value,
            message="Parent task dispatched child tasks",
            payload={"total_children": total_children},
        )
        return parent

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
        stmt: Select[tuple[Task]] = (
            select(Task)
            .where(Task.parent_task_id.is_(None))
            .order_by(Task.created_at.desc())
        )
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

    def list_children(self, parent_task_id: int) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.parent_task_id == parent_task_id)
            .order_by(Task.created_at.asc(), Task.id.asc())
        )
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
        active_statuses = {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.DISPATCHING,
            TaskStatus.PARTIALLY_RUNNING,
            TaskStatus.AGGREGATING,
        }

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

        if task.status in active_statuses:
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

        if task.status not in {
            TaskStatus.FAILED,
            TaskStatus.DEAD,
            TaskStatus.CANCELED,
        }:
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
                Task.task_role != TaskRole.PARENT,
                Task.status.in_([TaskStatus.PENDING, TaskStatus.RETRY_WAIT]),
                Task.scheduled_at <= now,
            )
            .order_by(Task.priority.desc(), Task.scheduled_at.asc(), Task.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        tasks = list(self.session.scalars(stmt))
        claimed: list[ClaimedTask] = []
        parent_ids_to_refresh: set[int] = set()

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
            if task.parent_task_id is not None and task.task_role == TaskRole.CHILD:
                parent_ids_to_refresh.add(task.parent_task_id)
            claimed.append(
                ClaimedTask(
                    id=task.id,
                    task_type=task.task_type,
                    task_role=task.task_role,
                    queue_name=task.queue_name,
                    priority=task.priority,
                    payload=task.payload_json,
                    attempt_no=task.attempt_no,
                    max_attempts=task.max_attempts,
                    timeout_seconds=task.timeout_seconds,
                    parent_task_id=task.parent_task_id,
                    shard_index=task.shard_index,
                )
            )

        for parent_task_id in parent_ids_to_refresh:
            self.refresh_parent_state(parent_task_id)

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

    def is_cancel_requested(
        self,
        task_id: int,
        parent_task_id: int | None = None,
    ) -> bool:
        task = self.session.get(Task, task_id)
        if task and task.cancel_requested:
            return True

        if parent_task_id is None:
            return False

        parent_task = self.session.get(Task, parent_task_id)
        if parent_task is None:
            return False
        return bool(
            parent_task.cancel_requested
            or parent_task.status in {TaskStatus.FAILED, TaskStatus.CANCELED, TaskStatus.DEAD}
        )

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
    ) -> Task:
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
        return task

    def mark_retry_wait(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        error_code: str,
        error_message: str,
        scheduled_at: datetime,
    ) -> Task:
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
        return task

    def mark_failed(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        error_code: str,
        error_message: str,
        attempt_status: AttemptStatus = AttemptStatus.FAILED,
    ) -> Task:
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
        return task

    def mark_dead(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
        error_code: str,
        error_message: str,
    ) -> Task:
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
        return task

    def mark_canceled(
        self,
        *,
        task_id: int,
        attempt_no: int,
        worker_id: str,
    ) -> Task:
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
        return task

    def refresh_parent_state(self, parent_task_id: int) -> Task | None:
        parent_task = self._get_parent_task_for_update(parent_task_id)
        summary = self._build_child_summary(parent_task_id)
        parent_task.total_children = summary["total"]
        parent_task.succeeded_children = summary["succeeded"]
        parent_task.failed_children = summary["failed"]
        parent_task.running_children = summary["running"]
        parent_task.child_summary = summary["detail"]
        if summary["total"] > 0:
            completed = summary["succeeded"] + summary["failed"]
            parent_task.progress = int((completed / summary["total"]) * 100)

        if parent_task.status in {TaskStatus.SUCCEEDED, TaskStatus.CANCELED, TaskStatus.DEAD}:
            return parent_task

        if summary["failed"] > 0:
            previous_status = parent_task.status.value
            parent_task.status = TaskStatus.FAILED
            parent_task.current_stage = "child_failed"
            parent_task.finished_at = utc_now()
            self._add_event(
                task_id=parent_task.id,
                event_type="PARENT_FAILED",
                from_status=previous_status,
                to_status=TaskStatus.FAILED.value,
                message="Parent task failed because at least one child failed",
            )
            return parent_task

        if parent_task.aggregation_dispatched:
            parent_task.status = TaskStatus.AGGREGATING
            parent_task.current_stage = "aggregating"
            return parent_task

        if summary["total"] > 0:
            parent_task.status = TaskStatus.PARTIALLY_RUNNING
            parent_task.current_stage = "children_running"

        return parent_task

    def schedule_aggregate_task_if_ready(
        self,
        *,
        parent_task_id: int,
        aggregate_task_type: str,
        queue_name: str,
        priority: int,
        max_attempts: int,
        timeout_seconds: int,
        created_by: str | None,
    ) -> Task | None:
        parent_task = self._get_parent_task_for_update(parent_task_id)
        if parent_task.status == TaskStatus.FAILED:
            return None
        if parent_task.aggregation_dispatched:
            return None
        if parent_task.total_children == 0:
            return None
        if parent_task.succeeded_children != parent_task.total_children:
            return None

        aggregate_task, _ = self.create_task(
            task_type=aggregate_task_type,
            queue_name=queue_name,
            biz_key=None,
            idempotency_key=None,
            priority=priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            scheduled_at=utc_now(),
            payload={"parent_task_id": parent_task_id},
            created_by=created_by,
            task_role=TaskRole.AGGREGATE,
            parent_task_id=parent_task_id,
        )
        previous_status = parent_task.status.value
        parent_task.status = TaskStatus.AGGREGATING
        parent_task.current_stage = "aggregating"
        parent_task.aggregation_dispatched = True
        self._add_event(
            task_id=parent_task.id,
            event_type="AGGREGATE_SCHEDULED",
            from_status=previous_status,
            to_status=TaskStatus.AGGREGATING.value,
            message="Aggregate task scheduled",
            payload={"aggregate_task_id": aggregate_task.id},
        )
        return aggregate_task

    def mark_parent_succeeded(
        self,
        *,
        parent_task_id: int,
        result: dict[str, Any] | None,
    ) -> Task:
        parent_task = self._get_parent_task_for_update(parent_task_id)
        summary = self._build_child_summary(parent_task_id)
        parent_task.total_children = summary["total"]
        parent_task.succeeded_children = summary["succeeded"]
        parent_task.failed_children = summary["failed"]
        parent_task.running_children = summary["running"]
        parent_task.child_summary = summary["detail"]
        previous_status = parent_task.status.value
        parent_task.status = TaskStatus.SUCCEEDED
        parent_task.current_stage = "completed"
        parent_task.progress = 100
        parent_task.result_json = result
        parent_task.finished_at = utc_now()
        self._add_event(
            task_id=parent_task.id,
            event_type="PARENT_SUCCEEDED",
            from_status=previous_status,
            to_status=TaskStatus.SUCCEEDED.value,
            message="Parent task aggregation completed successfully",
        )
        return parent_task

    def mark_parent_failed(
        self,
        *,
        parent_task_id: int,
        error_code: str,
        error_message: str,
    ) -> Task:
        parent_task = self._get_parent_task_for_update(parent_task_id)
        summary = self._build_child_summary(parent_task_id)
        parent_task.total_children = summary["total"]
        parent_task.succeeded_children = summary["succeeded"]
        parent_task.failed_children = summary["failed"]
        parent_task.running_children = summary["running"]
        parent_task.child_summary = summary["detail"]
        previous_status = parent_task.status.value
        parent_task.status = TaskStatus.FAILED
        parent_task.current_stage = "aggregate_failed"
        parent_task.error_code = error_code
        parent_task.error_message = self._truncate(error_message)
        parent_task.finished_at = utc_now()
        self._add_event(
            task_id=parent_task.id,
            event_type="PARENT_FAILED",
            from_status=previous_status,
            to_status=TaskStatus.FAILED.value,
            message="Parent task aggregation failed",
        )
        return parent_task

    def load_child_results(self, parent_task_id: int) -> list[dict[str, Any]]:
        child_tasks = self._get_child_tasks(parent_task_id)
        results: list[dict[str, Any]] = []
        for child_task in child_tasks:
            if child_task.status != TaskStatus.SUCCEEDED:
                continue
            results.append(
                {
                    "task_id": child_task.id,
                    "shard_index": child_task.shard_index,
                    "shard_key": child_task.shard_key,
                    "result": child_task.result_json,
                }
            )
        return results

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
        parent_ids_to_refresh: set[int] = set()
        for task in tasks:
            previous_status = task.status.value
            task.status = TaskStatus.PENDING
            task.lease_owner = None
            task.lease_until = None
            task.current_stage = "recovered"
            if task.parent_task_id is not None and task.task_role == TaskRole.CHILD:
                parent_ids_to_refresh.add(task.parent_task_id)
            self._add_event(
                task_id=task.id,
                event_type="LEASE_EXPIRED",
                from_status=previous_status,
                to_status=TaskStatus.PENDING.value,
                message="Expired lease recovered",
            )
        for parent_task_id in parent_ids_to_refresh:
            self.refresh_parent_state(parent_task_id)
        return len(tasks)

    def _get_running_owned_task(self, *, task_id: int, worker_id: str) -> Task:
        task = self.session.get(Task, task_id)
        if task is None or task.status != TaskStatus.RUNNING or task.lease_owner != worker_id:
            raise ValueError(f"Task {task_id} is not owned by worker {worker_id}")
        return task

    def _get_parent_task_for_update(self, parent_task_id: int) -> Task:
        parent_task = self.session.scalar(
            select(Task)
            .where(Task.id == parent_task_id)
            .with_for_update()
        )
        if parent_task is None or parent_task.task_role != TaskRole.PARENT:
            raise ValueError(f"Task {parent_task_id} is not a parent task")
        return parent_task

    def _get_child_tasks(self, parent_task_id: int) -> list[Task]:
        stmt = (
            select(Task)
            .where(
                Task.parent_task_id == parent_task_id,
                Task.task_role == TaskRole.CHILD,
            )
            .order_by(Task.shard_index.asc(), Task.id.asc())
        )
        return list(self.session.scalars(stmt))

    def _build_child_summary(self, parent_task_id: int) -> dict[str, Any]:
        child_tasks = self._get_child_tasks(parent_task_id)
        summary = {
            "pending": 0,
            "running": 0,
            "succeeded": 0,
            "failed": 0,
            "retry_wait": 0,
            "canceled": 0,
            "dead": 0,
        }

        for child_task in child_tasks:
            if child_task.status == TaskStatus.PENDING:
                summary["pending"] += 1
            elif child_task.status == TaskStatus.RUNNING:
                summary["running"] += 1
            elif child_task.status == TaskStatus.RETRY_WAIT:
                summary["retry_wait"] += 1
            elif child_task.status == TaskStatus.SUCCEEDED:
                summary["succeeded"] += 1
            elif child_task.status == TaskStatus.FAILED:
                summary["failed"] += 1
            elif child_task.status == TaskStatus.CANCELED:
                summary["failed"] += 1
                summary["canceled"] += 1
            elif child_task.status == TaskStatus.DEAD:
                summary["failed"] += 1
                summary["dead"] += 1

        return {
            "total": len(child_tasks),
            "succeeded": summary["succeeded"],
            "failed": summary["failed"],
            "running": summary["running"],
            "detail": summary,
        }

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
