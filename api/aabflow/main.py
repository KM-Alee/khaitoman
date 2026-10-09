"""FastAPI entry point: /api/v2 plus the compiled SPA on one local origin (T1.1)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from aabflow import config  # noqa: E402
from aabflow.repositories.sqlite import init_db  # noqa: E402



@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.schema_version = init_db(config.DB_PATH)
    yield


app = FastAPI(
    title="AabFlow",
    version=config.CONTRACT_VERSION,
    openapi_url="/api/v2/openapi.json",
    lifespan=lifespan,
)
api = APIRouter(prefix="/api/v2")


def _version(dist: str) -> str | None:
    try:
        return version(dist)
    except PackageNotFoundError:
        return None


@api.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "contract_version": config.CONTRACT_VERSION,
        "schema_version": getattr(app.state, "schema_version", None),
        "versions": {d: _version(d) for d in ("aquacrop", "ortools", "fastapi", "pydantic")},
    }


@api.get("/capabilities")
def capabilities() -> dict:
    return {
        "pilots": [],
        "exact_science": _version("aquacrop") is not None,
        "surrogate_gate": "not_run",
        "chat": {"key_configured": config.openai_key_configured(), "model": config.OPENAI_MODEL},
    }


@api.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_not_found(path: str) -> JSONResponse:
    return JSONResponse({"code": "NOT_FOUND", "detail": f"/api/v2/{path}"}, status_code=404)


app.include_router(api)

# SPA history fallback registered last, after API and asset routes.
if config.WEB_DIST.is_dir():
    app.mount("/static", StaticFiles(directory=config.WEB_DIST / "static"), name="static")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (config.WEB_DIST / path).resolve()
        if path and candidate.is_file() and config.WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(config.WEB_DIST / "index.html")
