from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Integer, String
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.domain.enums import AttemptStatus, ConfigRevisionStatus, TaskRole, TaskStatus
from app.infrastructure.datasource.relational.base import Base

PKInt = Integer().with_variant(Integer, "sqlite")


class Task(Base):
    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("task_type", "idempotency_key", name="uk_task_idempotency"),
        Index("idx_task_dispatch", "queue_name", "status", "scheduled_at", "priority", "id"),
        Index("idx_task_lease", "status", "lease_until"),
        Index("idx_task_biz", "task_type", "biz_key"),
        Index("idx_task_created", "created_at"),
        Index("idx_task_parent_dispatch", "parent_task_id", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    task_role: Mapped[TaskRole] = mapped_column(SAEnum(TaskRole, native_enum=False, length=16), default=TaskRole.STANDALONE, nullable=False)
    parent_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    biz_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    shard_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shard_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus, native_enum=False, length=32), default=TaskStatus.PENDING, nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    total_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    child_summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    aggregation_dispatched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    attempts: Mapped[list[TaskAttempt]] = relationship(back_populates="task")
    events: Mapped[list[TaskEvent]] = relationship(back_populates="task")


class TaskAttempt(Base):
    __tablename__ = "task_attempt"
    __table_args__ = (UniqueConstraint("task_id", "attempt_no", name="uk_task_attempt"),)

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pod_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(SAEnum(AttemptStatus, native_enum=False, length=16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    task: Mapped[Task] = relationship(back_populates="attempts")


class TaskEvent(Base):
    __tablename__ = "task_event"

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    event_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="events")


class RuntimeConfigRevision(Base):
    __tablename__ = "runtime_config_revision"
    __table_args__ = (UniqueConstraint("version_no", name="uk_runtime_config_revision_version"),)

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ConfigRevisionStatus] = mapped_column(SAEnum(ConfigRevisionStatus, native_enum=False, length=16), nullable=False, default=ConfigRevisionStatus.DRAFT, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_revision_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    change_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    published_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)


class RuntimeConfigState(Base):
    __tablename__ = "runtime_config_state"

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=False, default=1)
    active_revision_id: Mapped[Optional[int]] = mapped_column(ForeignKey("runtime_config_revision.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now())


class SystemSchedule(Base):
    __tablename__ = "system_schedule"
    __table_args__ = (
        UniqueConstraint("schedule_key", name="uk_system_schedule_key"),
        Index("idx_system_schedule_due", "enabled", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    schedule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    last_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    queue_name: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now())


class PolymarketSyncRun(Base):
    __tablename__ = "polymarket_sync_run"
    __table_args__ = (Index("idx_polymarket_sync_run_task", "task_id"),)

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cursor_in: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cursor_out: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)


class PolymarketSyncState(Base):
    __tablename__ = "polymarket_sync_state"
    __table_args__ = (
        UniqueConstraint("source", "resource", "scope", name="uk_polymarket_sync_state_scope"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    active_cursor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    last_snapshot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    last_event_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now())


class PolymarketEvent(Base):
    __tablename__ = "polymarket_event"
    __table_args__ = (
        UniqueConstraint("polymarket_event_id", name="uk_polymarket_event_id"),
        Index("idx_polymarket_event_slug", "slug"),
        Index("idx_polymarket_event_active_closed", "active", "closed"),
        Index("idx_polymarket_event_featured_volume", "featured", "volume"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    polymarket_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    closed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    archived: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    featured: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    restricted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    enable_order_book: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    neg_risk: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    liquidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_interest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_24hr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1wk: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1mo: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1yr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    last_snapshot_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class PolymarketEventSnapshot(Base):
    __tablename__ = "polymarket_event_snapshot"
    __table_args__ = (
        UniqueConstraint("polymarket_event_id", "snapshot_time", "snapshot_granularity", name="uk_polymarket_event_snapshot_bucket"),
        Index("idx_polymarket_event_snapshot_event_time", "polymarket_event_id", "snapshot_time"),
        Index("idx_polymarket_event_snapshot_time", "snapshot_time"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    polymarket_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    snapshot_granularity: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    closed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    archived: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    liquidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_interest: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_24hr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1wk: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1mo: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_1yr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class PolymarketEventRaw(Base):
    __tablename__ = "polymarket_event_raw"
    __table_args__ = (
        UniqueConstraint("polymarket_event_id", "payload_hash", name="uk_polymarket_event_raw_hash"),
        Index("idx_polymarket_event_raw_event", "polymarket_event_id"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    polymarket_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())


class SzdmJob(Base):
    __tablename__ = "szdm_job"
    __table_args__ = (
        UniqueConstraint("parent_task_id", name="uk_szdm_job_parent_task"),
        Index("idx_szdm_job_status_priority", "status", "priority", "updated_at"),
        Index("idx_szdm_job_report_status", "report_status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    parent_task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    job_s3_prefix: Mapped[str] = mapped_column(String(512), nullable=False)
    input_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reused_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_parallel_children: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    dispatch_batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    reuse_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=86400)
    report_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    report_s3_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    report_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    report_summary_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    report_metric_summary_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)


class SzdmItem(Base):
    __tablename__ = "szdm_item"
    __table_args__ = (
        UniqueConstraint("job_id", "item_key", "condition_key", name="uk_szdm_item_key_condition"),
        Index("idx_szdm_item_job_status_priority", "job_id", "status", "priority", "item_index"),
        Index("idx_szdm_item_child_task", "job_id", "child_task_id"),
        Index("idx_szdm_item_key", "job_id", "item_key"),
        Index("idx_szdm_item_condition", "job_id", "condition_key"),
    )

    id: Mapped[int] = mapped_column(PKInt, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    item_key: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    reuse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_CHECKED")
    child_task_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_s3_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    result_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    metrics_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    display_summary_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now(), onupdate=func.now())
