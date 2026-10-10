"""Read-only guided-demo manifest route (``GET /demo/session``).

``scripts/seed_demo_session.py`` (``make demo-seed``) executes the real pipeline through the API
and writes ``<data_dir>/demo/session.json`` with the IDs of the scenario, revisions, runs and
analyses it produced. This route serves that manifest unchanged and adds one server-computed
check: whether every referenced record still exists in *this* server's database (the manifest
lives next to a gitignored ``app.sqlite``, so a copied or stale manifest can point at nothing).
It never writes, never enqueues a job and never computes plan numbers of its own.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import Field, ValidationError

from aabflow.api.errors import DomainError
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import ErrorCode, StrictModel
from aabflow.services import analyses as analyses_svc
from aabflow.services.runs import run_row
from aabflow.services.scenarios import get_revision

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

MANIFEST_VERSION = 1
SEED_HINT = "run make demo-seed"


def manifest_path(data_dir: Path) -> Path:
    return Path(data_dir) / "demo" / "session.json"


class DemoApi(StrictModel):
    base_url: str
    contract_version: str
    versions: dict[str, str | None]


class DemoRevision(StrictModel):
    revision_id: str
    runs: dict[str, str] = Field(description="plan kind (B0, B1, P, R) -> run_id")


class DemoBudgetChange(DemoRevision):
    parent_revision_id: str
    changes: dict[str, Any] = Field(description="RevisionChange body used to derive the child")
    selection_reason: str = Field(
        description="Why this budget was used (it changed the selected P portfolio)"
    )
    tried_capital_budgets_pkr: list[int] = Field(default_factory=list)


class DemoAnalyses(StrictModel):
    frontier: str
    stress: str


class DemoRunDetail(StrictModel):
    """As returned by ``GET /runs/{id}`` when the seed ran; the run record stays authoritative."""

    plan_kind: str
    outcome: str
    solver_status: str
    created_at: str
    production_kg: float | None = None
    capital_commitment_pkr: float | None = None
    selected_intervention_instance_ids: list[str] = Field(default_factory=list)


class DemoManifest(StrictModel):
    manifest_version: Literal[1] = MANIFEST_VERSION
    created_at: str
    api: DemoApi
    pilot_id: str
    pilot_version: str
    season_id: str
    scenario_request: dict[str, Any]
    scenario_id: str
    base: DemoRevision
    budget_change: DemoBudgetChange
    analyses: DemoAnalyses
    comparison_id: str | None = None
    focus_field_id: str
    focus_field_reason: str
    decisive_date: date | None
    decisive_date_reason: str
    run_details: dict[str, DemoRunDetail] = Field(description="run_id -> details at seed time")
    timings_s: dict[str, float]
    notes: list[str] = Field(
        default_factory=list, description="Seed-time events, e.g. jobs resubmitted after a restart"
    )
    plan_turn_id: str | None = Field(
        None,
        description="Saved 'Plan my season' copilot turn (plan mode) run by the seed with --plan-goal; "
        "replayed from GET /copilot/turns/{id}/event-log",
    )
    plan_goal: str | None = Field(None, description="The goal sentence of the saved plan turn")
    plan_computed_at: str | None = Field(
        None, description="When the server finished the saved plan turn (its finished_at)"
    )

    def referenced_ids(self) -> dict[str, str]:
        """Every record ID the manifest points at -> its kind, in a stable order."""
        out: dict[str, str] = {self.scenario_id: "scenario"}
        for rev in (self.base, self.budget_change):
            out[rev.revision_id] = "revision"
        out[self.budget_change.parent_revision_id] = "revision"
        for rev in (self.base, self.budget_change):
            for rid in rev.runs.values():
                out[rid] = "run"
        out[self.analyses.frontier] = "analysis"
        out[self.analyses.stress] = "analysis"
        return out


class DemoSession(DemoManifest):
    """The seeded manifest plus a read-only availability check against this server's database."""

    available: dict[str, bool] = Field(description="referenced ID -> present in this database")
    missing_ids: list[str]
    complete: bool


def _no_manifest(detail: str) -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, detail, {})


def load_manifest(path: Path) -> DemoManifest:
    if not path.is_file():
        raise _no_manifest(f"No demo session manifest; {SEED_HINT}")
    try:
        return DemoManifest.model_validate(json.loads(path.read_text()))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        # ValidationError subclasses ValueError; named for clarity.
        raise _no_manifest(
            f"Demo session manifest is unreadable or invalid ({type(exc).__name__}); {SEED_HINT}"
        ) from exc


def _exists(conn: sqlite3.Connection, ident: str, kind: str) -> bool:
    try:
        if kind == "run":
            row = run_row(conn, ident)
            return (Path(row["run_dir"]) / "manifest.json").is_file()
        if kind == "analysis":
            analyses_svc.row(conn, ident)
            return True
        if kind == "revision":
            get_revision(conn, ident)
            return True
        return (
            conn.execute("SELECT 1 FROM scenarios WHERE scenario_id = ?", (ident,)).fetchone()
            is not None
        )
    except DomainError as exc:
        if exc.code is ErrorCode.NOT_FOUND:
            return False
        raise


def availability(conn: sqlite3.Connection, manifest: DemoManifest) -> dict[str, bool]:
    return {i: _exists(conn, i, k) for i, k in manifest.referenced_ids().items()}


@router.get("/demo/session", response_model=DemoSession)
def demo_session(state: State, conn: Conn) -> DemoSession:
    manifest = load_manifest(manifest_path(state.settings.data_dir))
    avail = availability(conn, manifest)
    missing = [i for i, ok in avail.items() if not ok]
    return DemoSession(
        **manifest.model_dump(), available=avail, missing_ids=missing, complete=not missing
    )
