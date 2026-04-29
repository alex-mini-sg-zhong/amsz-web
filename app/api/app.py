from __future__ import annotations

from fastapi import FastAPI

from app.api.middleware import RequestContextMiddleware
from app.api.routes.tasks import router as task_router
from app.core.config import get_settings
from app.db.session import create_tables


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.auto_create_tables:
        create_tables()

    app = FastAPI(title=settings.app_name)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(task_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
