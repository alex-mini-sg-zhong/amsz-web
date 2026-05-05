from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.domain.enums import AttemptStatus, TaskRole, TaskStatus

PKInt = Integer().with_variant(Integer, "sqlite")


class Task(Base):
    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("task_type", "idempotency_key", name="uk_task_idempotency"),
        Index(
            "idx_task_dispatch",
            "queue_name",
            "status",
            "scheduled_at",
            "priority",
            "id",
        ),
        Index("idx_task_lease", "status", "lease_until"),
        Index("idx_task_biz", "task_type", "biz_key"),
        Index("idx_task_created", "created_at"),
        Index("idx_task_parent_dispatch", "parent_task_id", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    task_role: Mapped[TaskRole] = mapped_column(
        SAEnum(TaskRole, native_enum=False, length=16),
        default=TaskRole.STANDALONE,
        nullable=False,
    )
    parent_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    biz_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    shard_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shard_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, length=32),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    child_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    aggregation_dispatched: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    attempts: Mapped[list["TaskAttempt"]] = relationship(back_populates="task")
    events: Mapped[list["TaskEvent"]] = relationship(back_populates="task")


class TaskAttempt(Base):
    __tablename__ = "task_attempt"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uk_task_attempt"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pod_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        SAEnum(AttemptStatus, native_enum=False, length=16),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    task: Mapped[Task] = relationship(back_populates="attempts")


class TaskEvent(Base):
    __tablename__ = "task_event"

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    task: Mapped[Task] = relationship(back_populates="events")
