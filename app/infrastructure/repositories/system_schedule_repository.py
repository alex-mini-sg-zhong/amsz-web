from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.datasource.relational.models import SystemSchedule


class SystemScheduleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def claim_due_schedules(self, *, now: datetime, limit: int) -> list[SystemSchedule]:
        stmt = (
            select(SystemSchedule)
            .where(
                SystemSchedule.enabled.is_(True),
                SystemSchedule.next_run_at <= now,
            )
            .order_by(SystemSchedule.next_run_at.asc(), SystemSchedule.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self.session.scalars(stmt))

    def create_schedule(
        self,
        *,
        schedule_key: str,
        task_type: str,
        interval_seconds: int,
        next_run_at: datetime,
        payload_json: dict | None = None,
        queue_name: str = "default",
        priority: int = 5,
        max_attempts: int = 3,
        timeout_seconds: int = 3600,
        enabled: bool = True,
    ) -> SystemSchedule:
        schedule = SystemSchedule(
            schedule_key=schedule_key,
            task_type=task_type,
            enabled=enabled,
            interval_seconds=interval_seconds,
            next_run_at=next_run_at,
            payload_json=payload_json or {},
            queue_name=queue_name,
            priority=priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
        )
        self.session.add(schedule)
        self.session.flush()
        return schedule

    def get_schedule(self, schedule_key: str) -> SystemSchedule | None:
        stmt = select(SystemSchedule).where(SystemSchedule.schedule_key == schedule_key)
        return self.session.scalar(stmt)

    def mark_schedule_dispatched(
        self,
        *,
        schedule: SystemSchedule,
        task_id: int,
        dispatched_at: datetime,
    ) -> None:
        schedule.last_task_id = task_id
        schedule.last_run_at = dispatched_at
        next_run_at = schedule.next_run_at or dispatched_at
        while next_run_at <= dispatched_at:
            next_run_at += timedelta(seconds=schedule.interval_seconds)
        schedule.next_run_at = next_run_at
