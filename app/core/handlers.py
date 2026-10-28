import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo.errors import AutoReconnect
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError

logger = logging.getLogger("tickethub")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def get_request_id(request: Request) -> str:
    """Reuse a sane inbound X-Request-ID, otherwise mint one (cached per request)."""
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        inbound = request.headers.get("x-request-id", "")
        rid = inbound if _REQUEST_ID_RE.match(inbound) else uuid.uuid4().hex
        request.state.request_id = rid
    return rid


def _error(request: Request, status: int, code: str, message: str, headers=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": get_request_id(request)}},
        headers=headers,
    )


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    return _error(request, exc.status_code, exc.code, exc.message, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"])
        parts.append(f"{loc}: {err['msg']}")
    return _error(request, 422, "VALIDATION_ERROR", "; ".join(parts) or "Invalid request")


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _error(request, exc.status_code, code, message, headers=getattr(exc, "headers", None))


async def _db_unavailable(request: Request, exc: AutoReconnect) -> JSONResponse:
    logger.error("database unavailable: %s", exc, extra={"request_id": get_request_id(request)})
    return _error(request, 503, "SERVICE_UNAVAILABLE", "Database is temporarily unavailable")


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", extra={"request_id": get_request_id(request)})
    return _error(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(AutoReconnect, _db_unavailable)
    app.add_exception_handler(Exception, _unhandled)
