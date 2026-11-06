"""Domain errors and the uniform error envelope: {"error": {"code", "message", "request_id"}}."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings

log = logging.getLogger("iam.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class BadRequest(AppError):
    status_code, code = 400, "bad_request"


class Unauthenticated(AppError):
    status_code, code = 401, "unauthenticated"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class ApprovalRequired(Conflict):
    code = "approval_required"


def _body(request: Request, code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # Report only location + message; never echo submitted values back.
        details = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        body = _body(request, "validation_error", "Request validation failed")
        body["error"]["details"] = details
        return JSONResponse(body, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthenticated", 403: "forbidden"}
        return JSONResponse(_body(request, codes.get(exc.status_code, "error"), "Request could not be processed"),
                            status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Stack traces (which can embed SQL parameters) are logged outside production only.
        log.error("unhandled error request_id=%s type=%s", getattr(request.state, "request_id", None), type(exc).__name__,
                  exc_info=exc if get_settings().app_env != "production" else None)
        return JSONResponse(_body(request, "internal_error", "Internal server error"), status_code=500)
