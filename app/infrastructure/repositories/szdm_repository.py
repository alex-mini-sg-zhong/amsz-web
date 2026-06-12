from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domain.enums import TaskRole, TaskStatus
from app.infrastructure.datasource.relational.models import SzdmItem, SzdmJob, Task
from app.infrastructure.repositories.task_repository import TaskRepository


class SzdmRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(
        self,
        *,
        parent_task_id: int,
        job_s3_prefix: str,
        input_s3_key: str,
        item_count: int,
        priority: int,
        max_parallel_children: int,
        dispatch_batch_size: int,
        reuse_window_seconds: int,
    ) -> SzdmJob:
        job = SzdmJob(
            parent_task_id=parent_task_id,
            status="PARTIALLY_RUNNING",
            priority=priority,
            job_s3_prefix=job_s3_prefix,
            input_s3_key=input_s3_key,
            item_count=item_count,
            max_parallel_children=max_parallel_children,
            dispatch_batch_size=dispatch_batch_size,
            reuse_window_seconds=reuse_window_seconds,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def create_items(self, *, job_id: int, items: list[dict[str, Any]], priority: int) -> list[SzdmItem]:
        rows: list[SzdmItem] = []
        for index, item in enumerate(items):
            row = SzdmItem(
                job_id=job_id,
                item_index=index,
                item_key=str(item["item_key"]),
                condition_key=str(item.get("condition_key") or "default"),
                priority=int(item["priority"]) if item.get("priority") is not None else priority,
                display_summary_json=item.get("display_summary"),
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows

    def get_job(self, job_id: int) -> SzdmJob | None:
        return self.session.get(SzdmJob, job_id)

    def get_job_by_parent_task_id(self, parent_task_id: int) -> SzdmJob | None:
        stmt = select(SzdmJob).where(SzdmJob.parent_task_id == parent_task_id)
        return self.session.scalar(stmt)

    def get_item(self, item_id: int) -> SzdmItem | None:
        return self.session.get(SzdmItem, item_id)

    def list_items(
        self,
        *,
        job_id: int,
        status: str | None,
        reuse_status: str | None,
        item_key: str | None,
        condition_key: str | None,
        limit: int,
        offset: int,
    ) -> list[SzdmItem]:
        stmt = select(SzdmItem).where(SzdmItem.job_id == job_id)
        if status:
            stmt = stmt.where(SzdmItem.status == status)
        if reuse_status:
            stmt = stmt.where(SzdmItem.reuse_status == reuse_status)
        if item_key:
            stmt = stmt.where(SzdmItem.item_key == item_key)
        if condition_key:
            stmt = stmt.where(SzdmItem.condition_key == condition_key)
        stmt = stmt.order_by(SzdmItem.priority.desc(), SzdmItem.item_index.asc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt))

    def claim_dispatchable_jobs(self, *, limit: int) -> list[SzdmJob]:
        stmt = (
            select(SzdmJob)
            .where(SzdmJob.status.in_(["PARTIALLY_RUNNING", "DISPATCHING"]))
            .order_by(SzdmJob.priority.desc(), SzdmJob.updated_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self.session.scalars(stmt))

    def dispatch_items_for_job(
        self,
        *,
        job: SzdmJob,
        task_repository: TaskRepository,
        queue_name: str,
        max_attempts: int,
        timeout_seconds: int,
        created_by: str | None,
        per_job_limit: int,
    ) -> int:
        self.refresh_job_counts(job.id)
        active_count = self._active_child_count(job.id)
        available_slots = max(0, job.max_parallel_children - active_count)
        limit = min(per_job_limit, job.dispatch_batch_size, available_slots)
        if limit <= 0:
            return 0

        stmt = (
            select(SzdmItem)
            .where(SzdmItem.job_id == job.id, SzdmItem.status == "PENDING")
            .order_by(SzdmItem.priority.desc(), SzdmItem.item_index.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        items = list(self.session.scalars(stmt))
        dispatched = 0
        for item in items:
            priority = max(job.priority, item.priority)
            task, created = task_repository.create_task(
                task_type="szdm.sub",
                queue_name=queue_name,
                biz_key=f"szdm:{job.id}:{item.id}",
                idempotency_key=f"szdm-sub:{job.id}:{item.id}",
                priority=priority,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                scheduled_at=utc_now(),
                payload={"job_id": job.id, "item_id": item.id},
                created_by=created_by,
                task_role=TaskRole.CHILD,
                parent_task_id=job.parent_task_id,
                shard_index=item.item_index,
                shard_key=item.item_key,
            )
            item.child_task_id = task.id
            item.status = "DISPATCHED"
            if created:
                dispatched += 1
        self.refresh_job_counts(job.id)
        return dispatched

    def schedule_aggregate_if_ready(
        self,
        *,
        job: SzdmJob,
        task_repository: TaskRepository,
        queue_name: str,
        max_attempts: int,
        timeout_seconds: int,
        created_by: str | None,
    ) -> Task | None:
        self.refresh_job_counts(job.id)
        if job.item_count == 0 or job.succeeded_count != job.item_count or job.report_status != "PENDING":
            return None
        task, created = task_repository.create_task(
            task_type="szdm.aggregate",
            queue_name=queue_name,
            biz_key=f"szdm-aggregate:{job.id}",
            idempotency_key=f"szdm-aggregate:{job.id}",
            priority=job.priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            scheduled_at=utc_now(),
            payload={"job_id": job.id},
            created_by=created_by,
            task_role=TaskRole.AGGREGATE,
            parent_task_id=job.parent_task_id,
        )
        job.report_status = "RUNNING"
        job.status = "AGGREGATING"
        parent = self.session.get(Task, job.parent_task_id)
        if parent is not None:
            parent.status = TaskStatus.AGGREGATING
            parent.current_stage = "szdm_aggregating"
            parent.aggregation_dispatched = True
        return task if created else None

    def mark_item_running(self, *, item_id: int, attempt_no: int) -> SzdmItem:
        item = self._require_item(item_id)
        item.status = "RUNNING"
        item.attempt_no = attempt_no
        item.started_at = item.started_at or utc_now()
        self.refresh_job_counts(item.job_id)
        return item

    def mark_item_succeeded(
        self,
        *,
        item_id: int,
        reuse_status: str,
        result_s3_key: str,
        result_timestamp: datetime,
        metrics: dict[str, Any],
        display_summary: dict[str, Any],
    ) -> SzdmItem:
        item = self._require_item(item_id)
        item.status = "SUCCEEDED"
        item.reuse_status = reuse_status
        item.result_s3_key = result_s3_key
        item.result_timestamp = result_timestamp
        item.metrics_json = metrics
        item.display_summary_json = display_summary
        item.error_code = None
        item.error_message = None
        item.finished_at = utc_now()
        self.refresh_job_counts(item.job_id)
        return item

    def mark_item_failed(self, *, item_id: int, error_code: str, error_message: str) -> SzdmItem:
        item = self._require_item(item_id)
        item.status = "FAILED"
        item.error_code = error_code
        item.error_message = error_message[:512]
        item.finished_at = utc_now()
        self.refresh_job_counts(item.job_id)
        return item

    def finish_report(
        self,
        *,
        job_id: int,
        report_s3_key: str,
        report_hash: str,
        summary: dict[str, Any],
        metric_summary: dict[str, Any],
    ) -> SzdmJob:
        job = self._require_job(job_id)
        job.report_status = "SUCCEEDED"
        job.report_s3_key = report_s3_key
        job.report_hash = report_hash
        job.report_summary_json = summary
        job.report_metric_summary_json = metric_summary
        job.status = "SUCCEEDED"
        job.finished_at = utc_now()
        parent = self.session.get(Task, job.parent_task_id)
        if parent is not None:
            parent.status = TaskStatus.SUCCEEDED
            parent.progress = 100
            parent.current_stage = "completed"
            parent.result_json = {"job_id": job.id, "report_s3_key": report_s3_key, "summary": summary}
            parent.finished_at = job.finished_at
        return job

    def update_job_priority(self, *, job_id: int, priority: int) -> SzdmJob:
        job = self._require_job(job_id)
        job.priority = priority
        pending_tasks = self._pending_child_tasks(job_id)
        for task in pending_tasks:
            task.priority = max(task.priority, priority)
        return job

    def update_item_priority(self, *, item_id: int, priority: int) -> SzdmItem:
        item = self._require_item(item_id)
        item.priority = priority
        if item.child_task_id is not None:
            task = self.session.get(Task, item.child_task_id)
            if task is not None and task.status in {TaskStatus.PENDING, TaskStatus.RETRY_WAIT}:
                task.priority = max(task.priority, priority)
        return item


    def list_all_items(self, *, job_id: int) -> list[SzdmItem]:
        stmt = select(SzdmItem).where(SzdmItem.job_id == job_id).order_by(SzdmItem.item_index.asc())
        return list(self.session.scalars(stmt))

    def refresh_job_counts(self, job_id: int) -> SzdmJob:
        job = self._require_job(job_id)
        rows = self.session.execute(
            select(SzdmItem.status, SzdmItem.reuse_status, func.count(SzdmItem.id))
            .where(SzdmItem.job_id == job_id)
            .group_by(SzdmItem.status, SzdmItem.reuse_status)
        ).all()
        status_counts: dict[str, int] = {}
        reuse_counts: dict[str, int] = {}
        for status, reuse_status, count in rows:
            status_counts[str(status)] = status_counts.get(str(status), 0) + int(count)
            reuse_counts[str(reuse_status)] = reuse_counts.get(str(reuse_status), 0) + int(count)
        job.dispatched_count = sum(status_counts.get(status, 0) for status in ("DISPATCHED", "RUNNING", "SUCCEEDED", "FAILED"))
        job.running_count = status_counts.get("RUNNING", 0) + status_counts.get("DISPATCHED", 0)
        job.succeeded_count = status_counts.get("SUCCEEDED", 0)
        job.failed_count = status_counts.get("FAILED", 0)
        job.reused_count = reuse_counts.get("REUSED", 0)
        job.generated_count = reuse_counts.get("GENERATED", 0)
        if job.failed_count > 0 and job.report_status == "PENDING":
            job.status = "FAILED"
            parent = self.session.get(Task, job.parent_task_id)
            if parent is not None:
                parent.status = TaskStatus.FAILED
                parent.current_stage = "szdm_item_failed"
                parent.finished_at = utc_now()
        return job

    def _active_child_count(self, job_id: int) -> int:
        return int(self.session.scalar(
            select(func.count(SzdmItem.id)).where(
                SzdmItem.job_id == job_id,
                SzdmItem.status.in_(["DISPATCHED", "RUNNING"]),
            )
        ) or 0)

    def _pending_child_tasks(self, job_id: int) -> list[Task]:
        stmt = (
            select(Task)
            .join(SzdmItem, SzdmItem.child_task_id == Task.id)
            .where(SzdmItem.job_id == job_id, Task.status.in_([TaskStatus.PENDING, TaskStatus.RETRY_WAIT]))
        )
        return list(self.session.scalars(stmt))

    def _require_job(self, job_id: int) -> SzdmJob:
        job = self.session.get(SzdmJob, job_id)
        if job is None:
            raise ValueError(f"SZDM job {job_id} not found")
        return job

    def _require_item(self, item_id: int) -> SzdmItem:
        item = self.session.get(SzdmItem, item_id)
        if item is None:
            raise ValueError(f"SZDM item {item_id} not found")
        return item
