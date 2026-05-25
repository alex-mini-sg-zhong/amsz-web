from __future__ import annotations

from typing import Any

from app.core.config import build_runtime_settings
from app.infrastructure.datasource.relational.models import RuntimeConfigRevision
from app.infrastructure.repositories.runtime_config_repository import RuntimeConfigRepository


class RuntimeConfigService:
    def __init__(self, repository: RuntimeConfigRepository) -> None:
        self.repository = repository

    def get_active_revision(self) -> RuntimeConfigRevision | None:
        return self.repository.get_active_revision()

    def list_revisions(self) -> list[RuntimeConfigRevision]:
        return self.repository.list_revisions()

    def get_revision(self, revision_id: int) -> RuntimeConfigRevision | None:
        return self.repository.get_revision(revision_id)

    def create_revision(
        self,
        *,
        config: dict[str, Any],
        created_by: str | None,
        change_note: str | None,
        schema_version: int,
        base_revision_id: int | None,
    ) -> RuntimeConfigRevision:
        build_runtime_settings(config)
        return self.repository.create_revision(
            config_json=config,
            created_by=created_by,
            change_note=change_note,
            schema_version=schema_version,
            base_revision_id=base_revision_id,
        )

    def activate_revision(
        self,
        *,
        revision_id: int,
        published_by: str | None,
    ) -> RuntimeConfigRevision:
        revision = self.repository.activate_revision(
            revision_id=revision_id,
            published_by=published_by,
        )
        return revision

    def archive_revision(self, revision_id: int) -> RuntimeConfigRevision:
        return self.repository.archive_revision(revision_id)

    def resolve_revision(self, revision: RuntimeConfigRevision) -> dict[str, Any]:
        settings = build_runtime_settings(revision.config_json)
        return settings.model_dump()
