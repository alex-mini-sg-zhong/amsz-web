from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.application.services.aggregate.task_orchestration_service import TaskOrchestrationService
from app.application.services.base.polymarket_command_service import PolymarketCommandService
from app.application.services.base.polymarket_query_service import PolymarketQueryService
from app.application.services.base.runtime_config_service import RuntimeConfigService
from app.application.services.base.task_command_service import TaskCommandService
from app.application.services.base.task_query_service import TaskQueryService
from app.core.config import get_settings
from app.infrastructure.datasource.relational.session import session_scope
from app.infrastructure.repositories.polymarket_repository import PolymarketRepository
from app.infrastructure.repositories.runtime_config_repository import RuntimeConfigRepository
from app.infrastructure.repositories.task_repository import TaskRepository


def get_db_session() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session


def get_task_command_service(session: Session = Depends(get_db_session)) -> TaskCommandService:
    return TaskCommandService(TaskRepository(session))


def get_task_query_service(session: Session = Depends(get_db_session)) -> TaskQueryService:
    return TaskQueryService(TaskRepository(session))


def get_task_orchestration_service(session: Session = Depends(get_db_session)) -> TaskOrchestrationService:
    return TaskOrchestrationService(TaskRepository(session))


def get_runtime_config_service(session: Session = Depends(get_db_session)) -> RuntimeConfigService:
    return RuntimeConfigService(RuntimeConfigRepository(session))


def get_polymarket_command_service(
    session: Session = Depends(get_db_session),
) -> PolymarketCommandService:
    return PolymarketCommandService(TaskRepository(session))


def get_polymarket_query_service(
    session: Session = Depends(get_db_session),
) -> PolymarketQueryService:
    return PolymarketQueryService(PolymarketRepository(session))


def get_request_id(request: Request) -> str:
    return str(request.state.request_id)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
