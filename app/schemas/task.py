from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=64)
    queue_name: str = Field(default="default", max_length=32)
    biz_key: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=5, ge=0, le=9)
    max_attempts: int = Field(default=3, ge=0, le=20)
    timeout_seconds: int = Field(default=3600, ge=1, le=7200)
    scheduled_at: datetime | None = None
    payload: dict[str, Any]


class TaskCreateResponse(BaseModel):
    task_id: int
    status: str
    message: str


class TaskDetailResponse(BaseModel):
    task_id: int
    task_type: str
    queue_name: str
    status: str
    progress: int
    current_stage: str | None
    attempt_no: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskCancelResponse(BaseModel):
    task_id: int
    cancel_requested: bool
    status: str


class TaskRetryResponse(BaseModel):
    task_id: int
    status: str
    message: str


class TaskEventResponse(BaseModel):
    event_type: str
    from_status: str | None
    to_status: str | None
    message: str | None
    event_payload: dict[str, Any] | None
    created_at: datetime


class TaskListItemResponse(BaseModel):
    task_id: int
    task_type: str
    queue_name: str
    status: str
    progress: int
    created_at: datetime
    finished_at: datetime | None
