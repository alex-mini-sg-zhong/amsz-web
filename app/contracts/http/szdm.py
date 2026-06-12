from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SzdmItemInput(BaseModel):
    item_key: str = Field(min_length=1, max_length=255)
    condition_key: str = Field(default="default", max_length=255)
    priority: int | None = Field(default=None, ge=0, le=9)
    payload: dict[str, Any] = Field(default_factory=dict)
    display_summary: dict[str, Any] | None = None


class SzdmJobCreateRequest(BaseModel):
    items: list[SzdmItemInput] = Field(min_length=1, max_length=10000)
    priority: int = Field(default=5, ge=0, le=9)
    max_parallel_children: int = Field(default=100, ge=1, le=10000)
    dispatch_batch_size: int = Field(default=50, ge=1, le=1000)
    reuse_window_seconds: int = Field(default=86400, ge=0)
    report_options: dict[str, Any] = Field(default_factory=dict)


class SzdmJobCreateResponse(BaseModel):
    job_id: int
    task_id: int
    status: str


class SzdmJobResponse(BaseModel):
    job_id: int
    parent_task_id: int
    status: str
    priority: int
    item_count: int
    dispatched_count: int
    running_count: int
    succeeded_count: int
    failed_count: int
    reused_count: int
    generated_count: int
    progress: int
    input_s3_key: str
    report_status: str
    report_s3_key: str | None
    report_summary: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class SzdmItemResponse(BaseModel):
    item_id: int
    item_index: int
    item_key: str
    condition_key: str
    status: str
    reuse_status: str
    priority: int
    child_task_id: int | None
    result_s3_key: str | None
    metrics: dict[str, Any] | None
    display_summary: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class SzdmPriorityRequest(BaseModel):
    priority: int = Field(ge=0, le=9)


class SzdmPriorityResponse(BaseModel):
    id: int
    priority: int
    message: str


class SzdmReportResponse(SzdmJobResponse):
    report_data: dict[str, Any] | None = None
