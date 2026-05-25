from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RuntimeConfigRevisionCreateRequest(BaseModel):
    config: dict[str, Any]
    change_note: str | None = Field(default=None, max_length=255)
    schema_version: int = Field(default=1, ge=1)
    base_revision_id: int | None = Field(default=None, ge=1)


class RuntimeConfigRevisionResponse(BaseModel):
    revision_id: int
    version_no: int
    status: str
    schema_version: int
    base_revision_id: int | None
    change_note: str | None
    config: dict[str, Any]
    resolved_config: dict[str, Any] | None = None
    created_by: str | None
    published_by: str | None
    created_at: datetime
    published_at: datetime | None


class RuntimeConfigRevisionListItemResponse(BaseModel):
    revision_id: int
    version_no: int
    status: str
    schema_version: int
    change_note: str | None
    created_by: str | None
    published_by: str | None
    created_at: datetime
    published_at: datetime | None


class RuntimeConfigActionResponse(BaseModel):
    revision_id: int
    status: str
    message: str
