"""Typed API errors (T9.3) and their JSON rendering."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from aabflow.domain.schemas import ErrorCode

STATUS = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.ASSET_UNAVAILABLE: 503,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.MODEL_INVALID: 500,
    ErrorCode.INVALID_PLAN: 500,
    ErrorCode.CANDIDATE_COVERAGE_LIMITED: 409,
}


class DomainError(Exception):
    """Raised by services; rendered as ``ApiError`` JSON with the T9.3 status."""

    def __init__(
        self,
        code: ErrorCode,
        detail: str,
        fields: dict[str, str] | None = None,
        *,
        extra: dict[str, Any] | None = None,
        status: int | None = None,
    ):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.fields = fields or {}
        self.extra = extra or {}
        self.status = status or STATUS[code]

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code.value,
            "detail": self.detail,
            "fields": self.fields,
        }
        out.update(self.extra)
        return out


def not_found(kind: str, ident: str) -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, f"unknown {kind} {ident!r}", {kind: ident})


def invalid(detail: str, fields: dict[str, str] | None = None) -> DomainError:
    return DomainError(ErrorCode.INVALID_INPUT, detail, fields)


def conflict(detail: str, diff: dict[str, Any] | None = None) -> DomainError:
    return DomainError(ErrorCode.VERSION_CONFLICT, detail, extra={"dependency_diff": diff or {}})


def unavailable(detail: str) -> DomainError:
    return DomainError(ErrorCode.ASSET_UNAVAILABLE, detail)


def _loc(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "request"


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for err in exc.errors():
            fields.setdefault(_loc(tuple(err.get("loc", ()))), err.get("msg", "invalid"))
        return JSONResponse(
            {
                "code": ErrorCode.INVALID_INPUT.value,
                "detail": "request failed validation",
                "fields": fields,
            },
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INVALID_INPUT
        return JSONResponse(
            {"code": code.value, "detail": str(exc.detail), "fields": {}},
            status_code=exc.status_code,
        )
