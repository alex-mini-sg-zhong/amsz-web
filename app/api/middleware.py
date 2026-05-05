from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.app_logging import get_logger


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or uuid4().hex
        request.state.request_id = request_id
        client_ip = request.client.host if request.client else "-"
        logger = get_logger(
            "app.api.request",
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
            client_ip=client_ip,
        )
        started = perf_counter()
        logger.info("Request started")
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "Request completed",
            extra={
                "status_code": response.status_code,
                "duration_ms": f"{duration_ms:.2f}",
            },
        )
        return response
