"""Read-only showcase routes for the landing page: ``GET /demo/headline`` and ``GET /ai-stack``.

``/demo/headline`` turns the seeded demo session's B0/B1/P runs into one story. Every figure is a
stored run metric or is derived here, in Python, from stored metrics; each comes back with its
unit and the run IDs it was computed from. The story key is chosen by fixed rules so the copy on
screen always matches the data.

``/ai-stack`` lists the four AI engines with one fact each, read from files and records that
already exist (review logs, the surrogate evaluation and timing benchmark, the latest plan run and
its candidate library, the copilot tool registry). A missing source yields
``status="unavailable"`` with a reason, never a default number.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from aabflow import config
from aabflow.api.demo import load_manifest, manifest_path
from aabflow.api.errors import DomainError
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import ErrorCode, StrictModel
from aabflow.services.runs import load_run
from aabflow.services.scenarios import get_revision

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

HEADLINE_METRICS = (
    "production_kg",
    "tail_min_service_ratio",
    "capital_commitment_pkr",
    "groundwater_m3",
)
Story = Literal["tail_tradeoff", "budget_efficiency", "plain_gain"]


class Figure(StrictModel):
    """One number shown on screen: a stored metric or a value derived from stored metrics."""

    value: float | None
    unit: str
    run_ids: list[str] = Field(description="the run(s) this figure is read or derived from")
    reason: str | None = None


class PlanFigures(StrictModel):
    run_id: str
    production_kg: Figure
    tail_min_service_ratio: Figure
    capital_commitment_pkr: Figure
    groundwater_m3: Figure


class DemoHeadline(StrictModel):
    story: Story
    pilot_id: str
    pilot_version: str
    season_id: str
    scenario_revision_id: str
    plans: dict[str, PlanFigures] = Field(description="B0, B1, P")
    capital_budget_pkr: Figure
    production_gain_pct_vs_b0: dict[str, Figure] = Field(description="B1, P vs B0 (%)")
    tail_service_change_pts: dict[str, Figure] = Field(
        description="B1, P vs B0 (percentage points)"
    )
    budget_used_fraction: Figure
    groundwater_above_b0: bool | None = Field(
        description="True when P pumps more groundwater than B0 (shown as a secondary line)"
    )
    run_created_at: dict[str, str] = Field(description="run_id -> computed time")


# ------------------------------------------------------------------ headline (pure)


def _metric_value(
    metrics: list[dict[str, Any]], metric_id: str
) -> tuple[float | None, str, str | None]:
    """Watercourse-level value of one metric; per-crop rows of the same unit are summed."""
    rows = [m for m in metrics if m["metric_id"] == metric_id and m.get("field_id") is None]
    if not rows:
        return None, "", f"{metric_id} not recorded for this run"
    bad = [m for m in rows if m.get("status") != "available" or m.get("value") is None]
    if bad:
        return None, rows[0]["unit"], bad[0].get("reason") or f"{metric_id} {bad[0].get('status')}"
    if len({m["unit"] for m in rows}) != 1:
        return None, rows[0]["unit"], f"{metric_id} rows use different units"
    total = rows[0]["value"] if len(rows) == 1 else sum(m["value"] for m in rows)
    return float(total), rows[0]["unit"], None


def plan_figures(run_id: str, metrics: list[dict[str, Any]]) -> PlanFigures:
    vals = {}
    for mid in HEADLINE_METRICS:
        v, unit, reason = _metric_value(metrics, mid)
        vals[mid] = Figure(value=v, unit=unit, run_ids=[run_id], reason=reason)
    return PlanFigures(run_id=run_id, **vals)


def _pct_gain(base: Figure, other: Figure) -> Figure:
    ids = base.run_ids + other.run_ids
    if base.value is None or other.value is None or base.value == 0:
        return Figure(value=None, unit="%", run_ids=ids, reason="baseline value missing or zero")
    return Figure(value=(other.value - base.value) / base.value * 100.0, unit="%", run_ids=ids)


def _pts_change(base: Figure, other: Figure) -> Figure:
    ids = base.run_ids + other.run_ids
    if base.value is None or other.value is None:
        return Figure(value=None, unit="pct_points", run_ids=ids, reason="service ratio missing")
    return Figure(value=(other.value - base.value) * 100.0, unit="pct_points", run_ids=ids)


def choose_story(b0: PlanFigures, b1: PlanFigures, p: PlanFigures, used: Figure) -> Story:
    t0, t1, tp = (x.tail_min_service_ratio.value for x in (b0, b1, p))
    if t0 is not None and t1 is not None and tp is not None and t1 < t0 and tp > t1:
        return "tail_tradeoff"
    if used.value is not None and used.value <= 0.5:
        return "budget_efficiency"
    return "plain_gain"


def build_headline(
    *,
    pilot_id: str,
    pilot_version: str,
    season_id: str,
    revision_id: str,
    budget_pkr: float | None,
    metrics_by_kind: dict[str, tuple[str, list[dict[str, Any]]]],
    created_at: dict[str, str],
) -> DemoHeadline:
    plans = {k: plan_figures(rid, ms) for k, (rid, ms) in metrics_by_kind.items()}
    b0, b1, p = plans["B0"], plans["B1"], plans["P"]
    cap = p.capital_commitment_pkr
    budget = Figure(
        value=budget_pkr,
        unit="PKR",
        run_ids=[p.run_id],
        reason=None if budget_pkr is not None else "scenario has no capital budget",
    )
    if cap.value is None or not budget_pkr:
        used = Figure(
            value=None, unit="fraction", run_ids=[p.run_id], reason="capital or budget missing"
        )
    else:
        used = Figure(value=cap.value / budget_pkr, unit="fraction", run_ids=[p.run_id])
    g0, gp = b0.groundwater_m3.value, p.groundwater_m3.value
    return DemoHeadline(
        story=choose_story(b0, b1, p, used),
        pilot_id=pilot_id,
        pilot_version=pilot_version,
        season_id=season_id,
        scenario_revision_id=revision_id,
        plans=plans,
        capital_budget_pkr=budget,
        production_gain_pct_vs_b0={
            k: _pct_gain(b0.production_kg, plans[k].production_kg) for k in ("B1", "P")
        },
        tail_service_change_pts={
            k: _pts_change(b0.tail_min_service_ratio, plans[k].tail_min_service_ratio)
            for k in ("B1", "P")
        },
        budget_used_fraction=used,
        groundwater_above_b0=None if g0 is None or gp is None else gp > g0,
        run_created_at=created_at,
    )


@router.get("/demo/headline", response_model=DemoHeadline)
def demo_headline(state: State, conn: Conn) -> DemoHeadline:
    """The landing story, from the seeded session's B0/B1/P runs (404 if any is missing)."""
    m = load_manifest(manifest_path(state.settings.data_dir))
    runs = {k: m.base.runs[k] for k in ("B0", "B1", "P") if k in m.base.runs}
    for k in ("B0", "B1", "P"):
        if k not in runs:
            raise DomainError(
                ErrorCode.NOT_FOUND, f"demo session has no {k} run; run make demo-seed", {}
            )
    loaded = {k: load_run(conn, rid) for k, rid in runs.items()}  # NOT_FOUND propagates as 404
    rev, _ = get_revision(conn, m.base.revision_id)
    return build_headline(
        pilot_id=m.pilot_id,
        pilot_version=m.pilot_version,
        season_id=m.season_id,
        revision_id=m.base.revision_id,
        budget_pkr=float(rev.request.capital_budget_pkr),
        metrics_by_kind={k: (lr.run_id, lr.json("metrics.json")) for k, lr in loaded.items()},
        created_at={lr.run_id: lr.row["created_at"] for lr in loaded.values()},
    )


# ------------------------------------------------------------------ AI stack


class AiFact(StrictModel):
    label: str
    value: float | str | None
    unit: str | None = None


class AiEngine(StrictModel):
    id: Literal["sees", "predicts", "plans", "explains"]
    label: str
    plain: str
    fact: str | None = Field(description="one plain sentence built from the figures below")
    fact_value: float | str | None
    unit: str | None
    facts: list[AiFact] = Field(default_factory=list)
    by_pilot: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="sees only: pilot_id -> {raw_polygons, selected}"
    )
    evidence_ref: str | None
    status: Literal["available", "unavailable"]
    reason: str | None = None


class AiStack(StrictModel):
    engines: list[AiEngine]


def _unavailable(eid: str, label: str, plain: str, reason: str) -> AiEngine:
    return AiEngine(
        id=eid,  # type: ignore[arg-type]
        label=label,
        plain=plain,
        fact=None,
        fact_value=None,
        unit=None,
        evidence_ref=None,
        status="unavailable",
        reason=reason,
    )


SEES = ("Sees", "AI finds every field from satellite images")
PREDICTS = ("Predicts", "A model we trained predicts crop yield in milliseconds")
PLANS = ("Plans", "An AI planner searches thousands of combinations and proves the best one")
EXPLAINS = ("Explains", "Ask in English or Urdu; it runs the real tools and shows its work")


def sees_engine(pilots_dir: Path, index: list[dict[str, Any]]) -> AiEngine:
    latest: dict[str, str] = {}
    for r in index:  # index order: the last listed version of each pilot is its latest
        latest[r["pilot_id"]] = r["pilot_version"]
    per: list[AiFact] = []
    by_pilot: dict[str, dict[str, int]] = {}
    raw = sel = 0
    checkpoint = None
    for pid, ver in sorted(latest.items()):
        d = pilots_dir / pid / ver
        try:
            s = json.loads((d / "review_log.json").read_text())["summary"]
            raw_n, sel_n = int(s["raw_polygons"]), int(s["selected"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        raw += raw_n
        sel += sel_n
        by_pilot[pid] = {"raw_polygons": raw_n, "selected": sel_n}
        per.append(AiFact(label=f"{pid} raw outlines", value=raw_n, unit="count"))
        per.append(AiFact(label=f"{pid} reviewed fields", value=sel_n, unit="count"))
        try:
            pv = json.loads((d / "manifest.json").read_text())["processing_versions"]
            checkpoint = checkpoint or pv.get("delineate_checkpoint")
        except (OSError, ValueError, KeyError, TypeError):
            pass
    if not per:
        return _unavailable("sees", *SEES, "no published pilot has a review log")
    per.append(
        AiFact(
            label="model", value=f"Delineate Anything ({checkpoint or 'checkpoint not recorded'})"
        )
    )
    return AiEngine(
        id="sees",
        label=SEES[0],
        plain=SEES[1],
        fact=f"{raw:,} possible fields found; {sel} kept after review",
        fact_value=raw,
        unit="count",
        facts=per,
        by_pilot=by_pilot,
        evidence_ref="review_log.json",
        status="available",
    )


def predicts_engine(data_dir: Path, evidence_dir: Path) -> AiEngine:
    models = data_dir / "models"
    try:
        version = json.loads((models / "surrogate-latest.json").read_text())["model_version"]
        ev = json.loads((models / version / "evaluation.json").read_text())
    except (OSError, ValueError, KeyError, TypeError):
        return _unavailable("predicts", *PREDICTS, "no trained surrogate evaluation on disk")
    facts = [
        AiFact(label="model", value=version),
        AiFact(label="training device", value=ev.get("training_device")),
    ]
    for crop, c in sorted((ev.get("crops") or {}).items()):
        nmae = (c.get("test") or {}).get("nmae")
        if nmae is not None:
            facts.append(
                AiFact(label=f"{crop} held-out error (nMAE)", value=float(nmae), unit="fraction")
            )
    ms = None
    try:
        bench = json.loads((evidence_dir / "benchmarks" / "p04-preview-timing.json").read_text())
        if bench.get("model_version") == version:
            ms = float(bench["preview"]["elapsed_ms_after_load"])
            facts.append(AiFact(label="one preview (measured)", value=ms, unit="ms"))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    exp = data_dir / "experiments"
    if exp.is_dir():
        n = sum(1 for p in exp.iterdir() if p.is_dir())
        facts.append(AiFact(label="crop-model experiments executed", value=n, unit="count"))
    return AiEngine(
        id="predicts",
        label=PREDICTS[0],
        plain=PREDICTS[1],
        fact=f"one yield estimate in {ms:.1f} ms"
        if ms is not None
        else "yield estimates in milliseconds",
        fact_value=ms,
        unit="ms" if ms is not None else None,
        facts=facts,
        evidence_ref="evidence/benchmarks/p04-preview-timing.json"
        if ms is not None
        else f"data/models/{version}/evaluation.json",
        status="available",
    )


def plans_engine(
    conn: sqlite3.Connection, libraries_dir: Path, preferred_run_id: str | None
) -> AiEngine:
    row = None
    if preferred_run_id:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE run_id = ?", (preferred_run_id,)
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE plan_kind = 'P' AND analysis_id IS NULL "
            "AND outcome = 'plan' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return _unavailable("plans", *PLANS, "no integrated plan (P) has been solved yet")
    try:
        lr = load_run(conn, row["run_id"])
    except DomainError as exc:
        return _unavailable("plans", *PLANS, f"latest plan run unreadable: {exc.detail}")
    res = lr.doc["result"]
    facts = [
        AiFact(label="solver status", value=res.get("solver_status")),
        AiFact(label="gap to proven best", value=res.get("relative_gap"), unit="fraction"),
        AiFact(label="solve time", value=res.get("solve_wall_ms"), unit="ms"),
    ]
    policies = None
    h = res.get("candidate_library_hash")
    if h:
        for p in libraries_dir.glob(f"*/*/{h}/library.json"):
            try:
                policies = int(json.loads(p.read_text())["build_stats"]["policies_retained"])
            except (OSError, ValueError, KeyError, TypeError):
                policies = None
            break
    if policies is not None:
        facts.insert(
            0, AiFact(label="candidate field policies searched", value=policies, unit="count")
        )
    proven = res.get("solver_status") == "OPTIMAL"
    fact = (
        f"{policies:,} options searched; best plan {'proven' if proven else res.get('solver_status')}"
        if policies is not None
        else f"best plan {'proven' if proven else res.get('solver_status')}"
    )
    return AiEngine(
        id="plans",
        label=PLANS[0],
        plain=PLANS[1],
        fact=fact,
        fact_value=policies,
        unit="count" if policies is not None else None,
        facts=facts,
        evidence_ref=lr.run_id,
        status="available",
    )


def explains_engine(copilot_available: bool, model: str) -> AiEngine:
    from aabflow.copilot.registry import tools_for_role

    n = len(tools_for_role("planner"))
    facts = [
        AiFact(label="tools it can run", value=n, unit="count"),
        AiFact(label="model", value=model),
    ]
    if not copilot_available:
        e = _unavailable("explains", *EXPLAINS, "no hosted-model key is configured on this server")
        e.facts = facts
        return e
    return AiEngine(
        id="explains",
        label=EXPLAINS[0],
        plain=EXPLAINS[1],
        fact=f"{n} real tools it can run, in English or Urdu",
        fact_value=n,
        unit="count",
        facts=facts,
        evidence_ref="/api/v2/copilot/status",
        status="available",
    )


_FILE_CACHE: dict[str, tuple[AiEngine, AiEngine]] = {}
_LOCK = threading.Lock()


def _file_engines(state: AppState) -> tuple[AiEngine, AiEngine]:
    key = str(state.settings.data_dir)
    with _LOCK:
        if key not in _FILE_CACHE:
            evidence = Path(state.settings.extra.get("evidence_dir") or config.ROOT / "evidence")
            _FILE_CACHE[key] = (
                sees_engine(state.settings.pilots_dir, state.pilots.index()),
                predicts_engine(state.settings.data_dir, evidence),
            )
        return _FILE_CACHE[key]


@router.get("/ai-stack", response_model=AiStack)
def ai_stack(state: State, conn: Conn) -> AiStack:
    from aabflow.copilot.router import status_view

    sees, predicts = _file_engines(state)
    preferred = None
    try:
        preferred = load_manifest(manifest_path(state.settings.data_dir)).base.runs.get("P")
    except DomainError:
        pass
    st = status_view(state)
    return AiStack(
        engines=[
            sees,
            predicts,
            plans_engine(conn, state.settings.libraries_dir, preferred),
            explains_engine(bool(st["configured"]), str(st["model"])),
        ]
    )
