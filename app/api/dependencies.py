from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import session_scope
from app.repositories.runtime_config_repository import RuntimeConfigRepository
from app.repositories.task_repository import TaskRepository
from app.services.runtime_config_service import RuntimeConfigService
from app.services.task_service import TaskService


def get_db_session() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session


def get_task_service(session: Session = Depends(get_db_session)) -> TaskService:
    repository = TaskRepository(session)
    return TaskService(repository)


def get_runtime_config_service(
    session: Session = Depends(get_db_session),
) -> RuntimeConfigService:
    repository = RuntimeConfigRepository(session)
    return RuntimeConfigService(repository)


def get_request_id(request: Request) -> str:
    return str(request.state.request_id)


def require_api_key(
    x_api_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
