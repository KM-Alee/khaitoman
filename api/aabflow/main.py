"""FastAPI entry point: /api/v2 plus the compiled SPA on one local origin (T1.1).

Route order: /api/v2 routers, the JSON 404 catch-all for unknown API paths,
/assets/pilots/... static package files, and only then the SPA history fallback.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from aabflow import config
from aabflow.api import errors
from aabflow.api.state import AppState
from aabflow.repositories.sqlite import init_db
from aabflow.services.catalog import Catalog
from aabflow.services.pilots import PilotRepository


def _routers() -> list[APIRouter]:
    from aabflow.api import (
        analyses,
        demo,
        impact,
        jobs,
        onboarding,
        packages,
        pilots,
        reports,
        runs,
        scenarios,
        showcase,
        surrogate,
        system,
    )
    from aabflow.copilot.router import router as copilot_router

    return [
        system.router,
        pilots.router,
        onboarding.router,
        packages.router,
        jobs.router,
        scenarios.router,
        impact.router,
        runs.router,
        analyses.router,
        surrogate.router,
        demo.router,
        showcase.router,
        reports.router,
        copilot_router,
    ]


def _dispatcher_cls():
    try:
        from aabflow.jobs.worker import Dispatcher
    except ImportError:
        return None
    return Dispatcher


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.settings_from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state: AppState = app.state.aab
        state.schema_version = init_db(settings.db_path)
        if settings.start_dispatcher and _dispatcher_cls() is not None:
            state.dispatcher = _dispatcher_cls()(settings)
            await state.dispatcher.start()
        try:
            yield
        finally:
            if state.dispatcher is not None:
                await state.dispatcher.stop()

    app = FastAPI(
        title="AabFlow",
        version=config.CONTRACT_VERSION,
        openapi_url="/api/v2/openapi.json",
        docs_url="/api/v2/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.aab = AppState(
        settings=settings,
        pilots=PilotRepository(settings.pilots_dir),
        catalog=Catalog(settings.libraries_dir),
    )
    errors.install(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "X-Contract-Version",
                "Idempotency-Key",
                "Last-Event-ID",
            ],
            expose_headers=["Content-Disposition", "X-Contract-Version"],
            max_age=600,
        )

    api = APIRouter(prefix="/api/v2")
    for r in _routers():
        api.include_router(r)

    @api.api_route(
        "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
    )
    def api_not_found(path: str) -> JSONResponse:
        return JSONResponse(
            {"code": "NOT_FOUND", "detail": f"/api/v2/{path}", "fields": {}}, status_code=404
        )

    app.include_router(api)

    from aabflow.api.pilots import assets_router

    app.include_router(assets_router)

    @app.api_route("/assets/{path:path}", methods=["GET"], include_in_schema=False)
    def asset_not_found(path: str) -> JSONResponse:
        return JSONResponse(
            {"code": "NOT_FOUND", "detail": f"/assets/{path}", "fields": {}}, status_code=404
        )

    # SPA history fallback registered last, after API and asset routes.
    dist = settings.web_dist
    if dist.is_dir():
        if (dist / "static").is_dir():
            app.mount("/static", StaticFiles(directory=dist / "static"), name="static")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
