from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_settings
from app.interfaces.http.middleware import RequestContextMiddleware
from app.interfaces.http.routes.polymarket import router as polymarket_router
from app.interfaces.http.routes.runtime_config import router as runtime_config_router
from app.interfaces.http.routes.szdm import router as szdm_router
from app.interfaces.http.routes.tasks import router as task_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(task_router)
    app.include_router(runtime_config_router)
    app.include_router(polymarket_router)
    app.include_router(szdm_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
