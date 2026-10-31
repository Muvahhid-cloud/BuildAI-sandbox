"""Uniform error envelope: {"error": {"code", "message", "details"}}.

Validation issues carry a JSON-pointer `path` so the UI can highlight the offending field.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


def _envelope(
    code: str, message: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}


def _json_pointer(loc: tuple[int | str, ...]) -> str:
    # Drop the leading "body"/"query"/"path" segment FastAPI adds.
    parts = (
        [str(p) for p in loc[1:]]
        if loc and loc[0] in {"body", "query", "path"}
        else list(map(str, loc))
    )
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            _envelope(exc.code, exc.message, exc.details), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"path": _json_pointer(tuple(err["loc"])), "message": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            _envelope("VALIDATION_ERROR", "Request validation failed", details),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(
            _envelope(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers
        )
