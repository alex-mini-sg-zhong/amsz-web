from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_runtime_config_service, require_api_key
from app.core.config import RuntimeConfigError, clear_settings_caches
from app.db.models import RuntimeConfigRevision
from app.schemas.runtime_config import (
    RuntimeConfigActionResponse,
    RuntimeConfigRevisionCreateRequest,
    RuntimeConfigRevisionListItemResponse,
    RuntimeConfigRevisionResponse,
)
from app.services.runtime_config_service import RuntimeConfigService

router = APIRouter(
    prefix="/api/v1/admin/runtime-config",
    tags=["runtime-config"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/active", response_model=RuntimeConfigRevisionResponse)
def get_active_runtime_config(
    service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigRevisionResponse:
    revision = service.get_active_revision()
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active revision not found",
        )
    return _build_revision_response(service, revision, include_resolved=True)


@router.get("/revisions", response_model=list[RuntimeConfigRevisionListItemResponse])
def list_runtime_config_revisions(
    service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> list[RuntimeConfigRevisionListItemResponse]:
    return [
        RuntimeConfigRevisionListItemResponse(
            revision_id=revision.id,
            version_no=revision.version_no,
            status=revision.status.value,
            schema_version=revision.schema_version,
            change_note=revision.change_note,
            created_by=revision.created_by,
            published_by=revision.published_by,
            created_at=revision.created_at,
            published_at=revision.published_at,
        )
        for revision in service.list_revisions()
    ]


@router.get("/revisions/{revision_id}", response_model=RuntimeConfigRevisionResponse)
def get_runtime_config_revision(
    revision_id: int,
    service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigRevisionResponse:
    revision = service.get_revision(revision_id)
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Revision not found",
        )
    return _build_revision_response(service, revision, include_resolved=False)


@router.post(
    "/revisions",
    response_model=RuntimeConfigRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_runtime_config_revision(
    payload: RuntimeConfigRevisionCreateRequest,
    request: Request,
    service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigRevisionResponse:
    created_by = request.headers.get("X-Client-Id")
    try:
        revision = service.create_revision(
            config=payload.config,
            created_by=created_by,
            change_note=payload.change_note,
            schema_version=payload.schema_version,
            base_revision_id=payload.base_revision_id,
        )
    except (RuntimeConfigError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _build_revision_response(service, revision, include_resolved=False)


@router.post("/revisions/{revision_id}/activate", response_model=RuntimeConfigActionResponse)
def activate_runtime_config_revision(
    revision_id: int,
    request: Request,
    service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigActionResponse:
    published_by = request.headers.get("X-Client-Id")
    try:
        revision = service.activate_revision(
            revision_id=revision_id,
            published_by=published_by,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    clear_settings_caches()
    return RuntimeConfigActionResponse(
        revision_id=revision.id,
        status=revision.status.value,
        message="runtime config revision activated",
    )


@router.post("/revisions/{revision_id}/archive", response_model=RuntimeConfigActionResponse)
def archive_runtime_config_revision(
    revision_id: int,
    service: RuntimeConfigService = Depends(get_runtime_config_service),
) -> RuntimeConfigActionResponse:
    try:
        revision = service.archive_revision(revision_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    clear_settings_caches()
    return RuntimeConfigActionResponse(
        revision_id=revision.id,
        status=revision.status.value,
        message="runtime config revision archived",
    )


def _build_revision_response(
    service: RuntimeConfigService,
    revision: RuntimeConfigRevision,
    *,
    include_resolved: bool,
) -> RuntimeConfigRevisionResponse:
    resolved_config = None
    if include_resolved:
        try:
            resolved_config = service.resolve_revision(revision)
        except RuntimeConfigError:
            resolved_config = None
    return RuntimeConfigRevisionResponse(
        revision_id=revision.id,
        version_no=revision.version_no,
        status=revision.status.value,
        schema_version=revision.schema_version,
        base_revision_id=revision.base_revision_id,
        change_note=revision.change_note,
        config=revision.config_json,
        resolved_config=resolved_config,
        created_by=revision.created_by,
        published_by=revision.published_by,
        created_at=revision.created_at,
        published_at=revision.published_at,
    )
