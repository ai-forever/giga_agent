from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from giga_agent.core.logging import get_logger

logger = get_logger("giga_agent.http")

_REQUEST_ID_HEADER = "X-Request-ID"
_BOUND_KEYS = ("request_id", "method", "path")
# Health/scrape endpoints hit every ~15s; don't spam the access log with them.
_SKIP_ACCESS_LOG_PATHS = ("/metrics", "/health")


class RequestLoggingContextMiddleware(BaseHTTPMiddleware):
    """Bind a per-request id + method/path into structlog contextvars.

    Makes every log line produced while handling an HTTP request on the
    giga_agent custom routes correlatable by ``request_id``, and emits a single
    access-style record on completion with status and duration. The bound
    contextvars are cleared in ``finally`` so they never bleed across requests
    sharing the worker context.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[_REQUEST_ID_HEADER] = request_id
            return response
        finally:
            if request.url.path not in _SKIP_ACCESS_LOG_PATHS:
                duration_ms = round((time.monotonic() - start) * 1000, 1)
                logger.info(
                    "http_request",
                    status=status_code,
                    duration_ms=duration_ms,
                )
            structlog.contextvars.unbind_contextvars(*_BOUND_KEYS)
