from __future__ import annotations

from datetime import datetime, timedelta

from app.core.app_logging import get_logger
from app.core.time import utc_now
from app.infrastructure.datasource.relational.models import SystemSchedule
from app.infrastructure.repositories.system_schedule_repository import SystemScheduleRepository
from app.infrastructure.repositories.task_repository import TaskRepository


class SystemSchedulerService:
    def __init__(self) -> None:
        self.logger = get_logger("app.application.services.aggregate.system_scheduler")

    def tick(
        self,
        *,
        schedule_repository: SystemScheduleRepository,
        task_repository: TaskRepository,
        max_due_schedules: int,
    ) -> int:
        now = utc_now()
        due_schedules = schedule_repository.claim_due_schedules(now=now, limit=max_due_schedules)
        created_count = 0
        for schedule in due_schedules:
            task, created = task_repository.create_task(
                task_type=schedule.task_type,
                queue_name=schedule.queue_name,
                biz_key=schedule.schedule_key,
                idempotency_key=self._build_schedule_idempotency_key(schedule),
                priority=schedule.priority,
                max_attempts=schedule.max_attempts,
                timeout_seconds=schedule.timeout_seconds,
                scheduled_at=now,
                payload=schedule.payload_json or {},
                created_by="system-scheduler",
            )
            schedule_repository.mark_schedule_dispatched(
                schedule=schedule,
                task_id=task.id,
                dispatched_at=now,
            )
            if created:
                created_count += 1
        return created_count

    @staticmethod
    def _build_schedule_idempotency_key(schedule: SystemSchedule) -> str:
        due_time = schedule.next_run_at or utc_now()
        return f"schedule:{schedule.schedule_key}:{due_time.isoformat()}"
