"""/health and /capabilities (T9.1): runtime readiness with no secrets."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from html import escape
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from aabflow import config
from aabflow.api.errors import invalid
from aabflow.api.models import Capabilities, FeatureStatus, Health
from aabflow.api.state import AppState, get_state
from aabflow.copilot.provider import configured_model

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]


@router.get("/access/ready", response_class=HTMLResponse, include_in_schema=False)
def access_ready(state: State, return_to: Annotated[str, Query(max_length=2048)]) -> HTMLResponse:
    """Browser landing after the edge's Access login; only return to an allowed UI.

    Cloudflare protects this route just like every other backend path. This route
    does not authenticate a caller or supply an Access credential.
    """
    try:
        target = urlsplit(return_to)
        origin = f"{target.scheme}://{target.netloc}"
        allowed = (
            target.scheme in {"http", "https"}
            and not target.username
            and not target.password
            and origin in state.settings.cors_origins
            and not any(ord(c) < 32 or c == "\\" for c in return_to)
        )
    except ValueError:
        allowed = False
    if not allowed:
        raise invalid(
            "Return URL must use a configured frontend origin", {"return_to": "origin not allowed"}
        )
    href = escape(return_to, quote=True)
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="0;url={href}">'
        "<title>AabFlow connection ready</title><main><h1>Return to AabFlow</h1>"
        f'<p><a href="{href}">Continue to the app</a></p></main></html>',
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        },
    )


def _version(dist: str) -> str | None:
    try:
        return version(dist)
    except PackageNotFoundError:
        return None


def _libraries_ready(state: AppState) -> list[tuple[str, str]]:
    out = []
    for pkg in state.pilots.published():
        for s in state.catalog.seasons():
            if state.catalog.latest_library_hash(pkg.pilot_id, s.season_id):
                out.append((pkg.pilot_id, s.season_id))
    return out


def surrogate_gate(state: AppState) -> str:
    """Gate status of the current surrogate (``surrogate-latest.json``) from its evaluation artifact.

    The science stream records ``passed`` (bool) plus per-crop ``gate_results``; ``gate_status`` is also
    accepted. No artifact -> ``not_run``; unreadable -> ``unreadable``.
    """
    models = state.settings.data_dir / "models"
    latest = models / "surrogate-latest.json"
    paths: list = []
    try:
        if latest.exists():
            paths = [models / json.loads(latest.read_text())["model_version"] / "evaluation.json"]
    except (ValueError, OSError, KeyError):
        return "unreadable"
    if not paths:
        paths = sorted(models.glob("surrogate*/evaluation.json"))
    statuses = []
    for p in paths:
        try:
            doc = json.loads(p.read_text())
        except (ValueError, OSError):
            statuses.append("unreadable")
            continue
        if "gate_status" in doc:
            statuses.append(str(doc["gate_status"]))
        elif isinstance(doc.get("passed"), bool):
            crops_ok = all(
                all(v for v in (c.get("gate_results") or {}).values())
                for c in (doc.get("crops") or {}).values()
            )
            statuses.append("passed" if doc["passed"] and crops_ok else "failed")
        else:
            statuses.append("unknown")
    if not statuses:
        return "not_run"
    if all(s == "passed" for s in statuses):
        return "passed"
    return "failed" if any(s == "failed" for s in statuses) else statuses[0]


@router.get("/health", response_model=Health)
def health(state: State) -> Health:
    db = "ok"
    try:
        conn = state.connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except (sqlite3.Error, OSError):
        db = "unavailable"
    disp = state.dispatcher
    running = bool(disp and disp.running)
    return Health(
        status="ok" if db == "ok" else "degraded",
        contract_version=config.CONTRACT_VERSION,
        schema_version=state.schema_version,
        database=db,
        pilots_published=len(state.pilots.index()),
        libraries_ready=len(_libraries_ready(state)),
        workers=state.settings.workers,
        dispatcher="running" if running else "stopped",
        versions={
            d: _version(d) for d in ("aquacrop", "ortools", "fastapi", "pydantic", "lightgbm")
        },
    )


def _fs(ok: bool, reason_if_not: str, partial: bool = False) -> FeatureStatus:
    if ok:
        return FeatureStatus(status="partial" if partial else "available")
    return FeatureStatus(status="not_available", reason=reason_if_not)


@router.get("/capabilities", response_model=Capabilities)
def capabilities(state: State) -> Capabilities:
    pilots = [
        {
            "pilot_id": r["pilot_id"],
            "pilot_version": r["pilot_version"],
            "name": str(r.get("name", r["pilot_id"])),
        }
        for r in state.pilots.index()
    ]
    libs = _libraries_ready(state)
    gate = surrogate_gate(state)
    has_pilot = bool(pilots)
    has_lib = bool(libs)
    onboarding = importlib.util.find_spec("aabflow.ingestion.onboarding") is not None
    no_lib = "no published candidate library for any pilot/season"
    features = {
        "F01": _fs(has_pilot, "no published pilot package"),
        "F04": _fs(bool(state.catalog.seasons()), "no published season catalog"),
        "F07": _fs(has_lib, no_lib),
        "F08": _fs(has_lib, no_lib),
        "F09": _fs(has_lib, no_lib),
        "F10": _fs(has_lib, no_lib),
        "F11": _fs(has_lib, no_lib),
        "F12": FeatureStatus(
            status="available" if gate == "passed" else "not_available",
            reason=None if gate == "passed" else f"surrogate evaluation gate: {gate}",
        ),
        "F13": _fs(has_lib, no_lib),
        "F14": _fs(has_lib, no_lib),
        "F15": _fs(has_lib, no_lib),
        "F16": _fs(has_lib, no_lib),
        "F17": _fs(has_pilot, "no published pilot package"),
        "F03": _fs(onboarding, "ingestion onboarding pipeline not installed"),
        # Hosted chat needs a configured key; AT17 (30x3 evaluation) is not certified, so never "available".
        "copilot": FeatureStatus(
            status="partial",
            reason="hosted copilot configured; the 30-case evaluation (AT17) has not passed yet",
        )
        if config.openai_key_configured()
        else FeatureStatus(
            status="not_available",
            reason="no hosted-model key is configured; saved results and controls work offline",
        ),
    }
    return Capabilities(
        pilots=pilots,
        exact_science=_version("aquacrop") is not None,
        surrogate_gate=gate,
        # Mirrors features.copilot; reachability of the hosted model is only known after a call, so
        # "connected" is null (not measured) instead of a fixed false.
        chat={
            "key_configured": config.openai_key_configured(),
            "model": configured_model(),
            "available": features["copilot"].status != "not_available",
            "status": features["copilot"].status,
            "reason": features["copilot"].reason,
            "connected": None,
            "status_url": "/api/v2/copilot/status",
        },
        features=features,
    )
