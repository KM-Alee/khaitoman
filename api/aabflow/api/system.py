"""/health and /capabilities (T9.1): runtime readiness with no secrets."""

from __future__ import annotations

import importlib.util
import json
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

from fastapi import APIRouter, Depends

from aabflow import config
from aabflow.api.models import Capabilities, FeatureStatus, Health
from aabflow.api.state import AppState, get_state

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]


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
    """Gate status as published by the science stream's evaluation artifact, else not_run."""
    models = state.settings.data_dir / "models"
    statuses = []
    for p in sorted(models.glob("surrogate*/**/evaluation.json")):
        try:
            statuses.append(str(json.loads(p.read_text()).get("gate_status", "unknown")))
        except (ValueError, OSError):
            statuses.append("unreadable")
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
    except Exception:
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
        versions={d: _version(d) for d in ("aquacrop", "ortools", "fastapi", "pydantic", "lightgbm")},
    )


def _fs(ok: bool, reason_if_not: str, partial: bool = False) -> FeatureStatus:
    if ok:
        return FeatureStatus(status="partial" if partial else "available")
    return FeatureStatus(status="not_available", reason=reason_if_not)


@router.get("/capabilities", response_model=Capabilities)
def capabilities(state: State) -> Capabilities:
    pilots = [
        {"pilot_id": r["pilot_id"], "pilot_version": r["pilot_version"], "name": str(r.get("name", r["pilot_id"]))}
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
        "copilot": FeatureStatus(status="not_available", reason="copilot is implemented last (M7)"),
    }
    return Capabilities(
        pilots=pilots,
        exact_science=_version("aquacrop") is not None,
        surrogate_gate=gate,
        chat={"key_configured": config.openai_key_configured(), "model": config.OPENAI_MODEL, "connected": False},
        features=features,
    )
