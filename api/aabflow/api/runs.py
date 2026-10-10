"""Run, timeline, comparison and run-derived view routes (T9.1, F14–F16)."""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, Header, Query

from aabflow.api.errors import not_found
from aabflow.api.idempotency import run_idempotent
from aabflow.api.state import AppState, get_conn, get_state
from aabflow.domain.schemas import CONTRACT_VERSION, MetricValue, RunResult, StrictModel
from aabflow.services import insights
from aabflow.services.metrics import METRICS_VERSION, REGISTRY
from aabflow.services.runs import SERIES, list_runs, load_run

router = APIRouter()
State = Annotated[AppState, Depends(get_state)]
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


class RunSummary(StrictModel):
    run_id: str
    plan_kind: str
    outcome: str
    solver_status: str
    scenario_revision_id: str
    created_at: str
    pilot_id: str
    pilot_version: str
    season_id: str
    analysis_id: str | None = None
    job_id: str | None = None


class RunList(StrictModel):
    runs: list[RunSummary]


class RunView(StrictModel):
    run: RunResult
    metrics: list[MetricValue]
    selection: dict[str, Any] | None
    meta: dict[str, Any]
    label: str | None = None
    analysis_id: str | None = None
    job_id: str | None = None
    software: dict[str, Any]
    bundle_verified: bool


class SeriesOut(StrictModel):
    series_id: str
    entity_id: str
    label: str
    unit: str
    kind: str
    source: Literal["ledger", "crop_model", "weather"]
    values: list[float | None]


class Timeline(StrictModel):
    run_id: str
    field_id: str | None
    state_id: str
    resolution: Literal["daily", "weekly"]
    dates: list[str]
    series: list[SeriesOut]
    edges: list[SeriesOut]
    ponds: list[SeriesOut]
    windows: list[dict[str, Any]]
    note: str


class MetricDefinitions(StrictModel):
    metrics_version: str
    definitions: list[dict[str, Any]]


class ComparisonRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    run_ids: list[str]


@router.get("/metrics/definitions", response_model=MetricDefinitions)
def metric_definitions() -> MetricDefinitions:
    return MetricDefinitions(
        metrics_version=METRICS_VERSION, definitions=[d.as_dict() for d in REGISTRY.values()]
    )


@router.get("/runs", response_model=RunList)
def runs(
    conn: Conn,
    pilot_id: str | None = None,
    pilot_version: str | None = None,
    scenario_revision_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> RunList:
    return RunList(
        runs=list_runs(
            conn,
            pilot_id=pilot_id,
            pilot_version=pilot_version,
            scenario_revision_id=scenario_revision_id,
            limit=limit,
        )
    )


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, conn: Conn) -> RunView:
    r = load_run(conn, run_id)
    return RunView(
        run=r.result,
        metrics=r.metrics(),
        selection=r.json("selection.json"),
        meta=r.meta,
        label=r.doc.get("label"),
        analysis_id=r.doc.get("analysis_id"),
        job_id=r.doc.get("job_id"),
        software=r.doc.get("software", {}),
        bundle_verified=True,
    )


@router.get("/runs/{run_id}/solver")
def get_solver(run_id: str, conn: Conn) -> dict:
    return load_run(conn, run_id).json("solver.json")


@router.get("/runs/{run_id}/coverage")
def get_coverage(run_id: str, conn: Conn) -> dict:
    return load_run(conn, run_id).json("coverage.json")


@router.get("/runs/{run_id}/validation")
def get_validation(run_id: str, conn: Conn) -> dict:
    return load_run(conn, run_id).json("validation.json")


def _pivot(df: pd.DataFrame, dates: list[str], weekly: bool) -> list[float | None]:
    s = df.groupby("date")["value"].sum()
    return [float(s[d]) if d in s.index else None for d in dates]


STATE_SERIES = {
    "canopy_fraction",
    "biomass_kg_ha",
    "soil_profile_water_mm",
    "root_zone_water_mm",
    "pond_inventory_m3",
}


def _series_out(df: pd.DataFrame, sid: str, ent: str, dates: list[str], weekly: bool) -> SeriesOut:
    label, unit, kind = SERIES.get(sid, (sid.replace("_", " "), "m3", "water"))
    if sid == "edge_delivered_m3":
        label, unit, kind = ("Edge intake (routed canal flow)", "m3", "water")
    if sid == "pond_inventory_m3":
        label, unit, kind = ("Pond inventory (end of day)", "m3", "water")
    src = "crop_model" if kind == "crop" else ("weather" if kind == "weather" else "ledger")
    vals = _pivot(df, dates, weekly)
    if sid == "pond_inventory_m3":  # carry state forward between event days
        last = None
        filled = []
        for v in vals:
            last = v if v is not None else last
            filled.append(last)
        vals = filled
    return SeriesOut(
        series_id=sid, entity_id=ent, label=label, unit=unit, kind=kind, source=src, values=vals
    )


@router.get("/runs/{run_id}/timeline", response_model=Timeline)
def timeline(
    run_id: str,
    conn: Conn,
    state: State,
    field_id: str | None = None,
    resolution: Literal["daily", "weekly"] = "daily",
) -> Timeline:
    r = load_run(conn, run_id)
    tl = r.timeline()
    meta = r.meta
    pkg = state.pilots.package(meta["pilot_id"], meta["pilot_version"])
    if field_id is not None and field_id not in pkg.fields:
        raise not_found("field_id", field_id)
    if tl.empty:
        dates: list[str] = []
    else:
        dates = sorted(tl["date"].unique())
    if resolution == "weekly" and dates:
        tl = tl.copy()
        wk = pd.to_datetime(tl["date"]).dt.to_period("W-SUN").dt.start_time.dt.date.astype(str)
        state_rows = tl["series_id"].isin(STATE_SERIES)
        flows = (
            tl[~state_rows]
            .assign(date=wk[~state_rows])
            .groupby(["date", "field_id", "entity_id", "series_id"], dropna=False)["value"]
            .sum()
            .reset_index()
        )
        st = (
            tl[state_rows]
            .assign(date=wk[state_rows])
            .sort_values("date")
            .groupby(["date", "field_id", "entity_id", "series_id"], dropna=False)["value"]
            .last()
            .reset_index()
        )
        tl = pd.concat([flows, st], ignore_index=True)
        dates = sorted(tl["date"].unique())
    series, edges, ponds = [], [], []
    if not tl.empty:
        if field_id is not None:
            ft = tl[tl["field_id"] == field_id]
            for sid, g in ft.groupby("series_id"):
                series.append(_series_out(g, sid, field_id, dates, resolution == "weekly"))
        net = tl[tl["field_id"].isna()]
        for (sid, ent), g in net.groupby(["series_id", "entity_id"]):
            out = _series_out(g, sid, ent, dates, resolution == "weekly")
            (edges if sid == "edge_delivered_m3" else ponds).append(out)
    season = meta["season_id"]
    wins = [
        {
            "window_id": w.window_id,
            "field_id": w.field_id,
            "start": w.start.isoformat(),
            "end": w.end.isoformat(),
            "basis": w.basis.value,
            "rate_m3_s": w.rate_m3_s,
            "volume_cap_m3": w.volume_cap_m3,
            "verification": w.verification,
        }
        for w in pkg.roster.get(season, [])
        if field_id is None or w.field_id == field_id
    ]
    return Timeline(
        run_id=run_id,
        field_id=field_id,
        state_id=meta["typical_state"],
        resolution=resolution,
        dates=list(dates),
        series=series,
        edges=edges,
        ponds=ponds,
        windows=wins,
        note="Crop series are exact AquaCrop outputs for the selected policy; water series are the "
        "original-precision ledger aggregated by local day. Missing values are gaps, not zeros. "
        "Weekly values are display aggregations.",
    )


@router.post("/comparisons", status_code=201)
def create_comparison(body: ComparisonRequest, conn: Conn, idem: IdemKey = None):
    def create():
        res = insights.compare(conn, body.run_ids)
        cid = insights.store_comparison(conn, res)
        return 201, {"comparison_id": cid, **res}

    return run_idempotent(conn, "POST /comparisons", idem, body.model_dump(mode="json"), create)


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: str, conn: Conn) -> dict:
    res = insights.get_comparison(conn, comparison_id)
    if res is None:
        raise not_found("comparison_id", comparison_id)
    return {"comparison_id": comparison_id, **res}


@router.get("/runs/{run_id}/accounting")
def run_accounting(run_id: str, conn: Conn) -> dict:
    return insights.accounting(load_run(conn, run_id))


@router.get("/runs/{run_id}/equity")
def run_equity(run_id: str, conn: Conn, state: State, baseline_run_id: str | None = None) -> dict:
    base = load_run(conn, baseline_run_id) if baseline_run_id else None
    return insights.equity(conn, load_run(conn, run_id), base, state.pilots)


@router.get("/runs/{run_id}/economics")
def run_economics(run_id: str, conn: Conn, state: State) -> dict:
    return insights.economics(load_run(conn, run_id), state.pilots)


@router.get("/runs/{run_id}/action-plan")
def run_action_plan(run_id: str, conn: Conn, state: State) -> dict:
    return insights.action_plan(load_run(conn, run_id), state.pilots)


@router.get("/runs/{run_id}/explanations")
def run_explanations(run_id: str, conn: Conn, state: State) -> dict:
    from aabflow.services.explanations import explain
    from aabflow.services.runs import RunContext

    rc = RunContext(state.settings, state.pilots, state.catalog)
    return explain(rc, load_run(conn, run_id))
