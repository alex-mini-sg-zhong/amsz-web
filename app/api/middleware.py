from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.logging import get_logger


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or uuid4().hex
        request.state.request_id = request_id
        logger = get_logger("app.api.request", request_id=request_id)
        started = perf_counter()
        logger.info("Request started")
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "Request completed "
            f"status={response.status_code} duration_ms={duration_ms:.2f}"
        )
        return response
