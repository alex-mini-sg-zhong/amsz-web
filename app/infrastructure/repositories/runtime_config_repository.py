from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domain.enums import ConfigRevisionStatus
from app.infrastructure.datasource.relational.models import RuntimeConfigRevision, RuntimeConfigState


class RuntimeConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_active_revision(self) -> RuntimeConfigRevision | None:
        state = self._get_or_create_state()
        if state.active_revision_id is None:
            return None
        return self.session.get(RuntimeConfigRevision, state.active_revision_id)

    def get_revision(self, revision_id: int) -> RuntimeConfigRevision | None:
        return self.session.get(RuntimeConfigRevision, revision_id)

    def list_revisions(self) -> list[RuntimeConfigRevision]:
        stmt = select(RuntimeConfigRevision).order_by(RuntimeConfigRevision.version_no.desc())
        return list(self.session.scalars(stmt))

    def create_revision(
        self,
        *,
        config_json: dict[str, Any],
        created_by: str | None,
        change_note: str | None,
        schema_version: int,
        base_revision_id: int | None,
    ) -> RuntimeConfigRevision:
        if base_revision_id is not None:
            active_revision = self.get_active_revision()
            active_revision_id = active_revision.id if active_revision is not None else None
            if base_revision_id != active_revision_id:
                raise ValueError("base_revision_id does not match the active revision")

        next_version_no = (self.session.scalar(select(func.max(RuntimeConfigRevision.version_no))) or 0) + 1
        revision = RuntimeConfigRevision(
            version_no=next_version_no,
            status=ConfigRevisionStatus.DRAFT,
            schema_version=schema_version,
            base_revision_id=base_revision_id,
            change_note=change_note,
            config_json=config_json,
            created_by=created_by,
        )
        self.session.add(revision)
        self.session.flush()
        return revision

    def activate_revision(
        self,
        *,
        revision_id: int,
        published_by: str | None,
    ) -> RuntimeConfigRevision:
        revision = self._require_revision(revision_id)
        state = self._get_or_create_state()

        current_active = None
        if state.active_revision_id is not None:
            current_active = self.session.get(RuntimeConfigRevision, state.active_revision_id)
        if current_active is not None and current_active.id != revision.id:
            current_active.status = ConfigRevisionStatus.ARCHIVED

        revision.status = ConfigRevisionStatus.ACTIVE
        revision.published_by = published_by
        revision.published_at = utc_now()
        state.active_revision_id = revision.id
        return revision

    def archive_revision(self, revision_id: int) -> RuntimeConfigRevision:
        revision = self._require_revision(revision_id)
        state = self._get_or_create_state()
        if state.active_revision_id == revision.id:
            raise ValueError("Active revision cannot be archived")
        revision.status = ConfigRevisionStatus.ARCHIVED
        return revision

    def get_revision_config(self, revision_id: int) -> dict[str, Any]:
        revision = self._require_revision(revision_id)
        return revision.config_json

    def _get_or_create_state(self) -> RuntimeConfigState:
        state = self.session.get(RuntimeConfigState, 1)
        if state is None:
            state = RuntimeConfigState(id=1, active_revision_id=None)
            self.session.add(state)
            self.session.flush()
        return state

    def _require_revision(self, revision_id: int) -> RuntimeConfigRevision:
        revision = self.session.get(RuntimeConfigRevision, revision_id)
        if revision is None:
            raise ValueError(f"Runtime config revision {revision_id} not found")
        return revision
