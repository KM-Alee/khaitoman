"""Dataset builders: copy authoritative service results into chartable datasets.

Each builder takes the JSON a /api/v2 route returned to a tool, copies the values
(no recomputation except where noted as a server-side sum or ordering), attaches
units, basis labels and the run/analysis/comparison IDs, and registers the dataset
in the turn's store. Builders return the compact descriptor the model sees.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from aabflow.copilot.visuals import Column, Dataset, DatasetSource, Encoding

PLAN_NAMES = {
    "B0": "B0 fixed roster",
    "B1": "B1 no new capital",
    "P": "P integrated plan",
    "R": "R robust plan",
}
PLAN_NAMES_UR = {
    "B0": "B0 مقررہ باری",
    "B1": "B1 بغیر نئی سرمایہ کاری",
    "P": "P مربوط منصوبہ",
    "R": "R مضبوط منصوبہ",
}
GROUP_UR = {"head": "سر", "middle": "درمیان", "tail": "دم"}

# Column labels (English, Urdu). Units come from the services, never from here.
LABELS: dict[str, tuple[str, str]] = {
    "field": ("Field", "کھیت"),
    "field_id": ("Field ID", "کھیت آئی ڈی"),
    "group": ("Canal position", "نہر پر مقام"),
    "plan": ("Plan", "منصوبہ"),
    "plan_kind": ("Plan kind", "منصوبے کی قسم"),
    "run_id": ("Run", "رن"),
    "metric": ("Measure", "پیمانہ"),
    "metric_id": ("Metric ID", "میٹرک آئی ڈی"),
    "value": ("Value", "قدر"),
    "unit": ("Unit", "اکائی"),
    "status": ("Status", "حالت"),
    "production_kg": ("Crop production", "فصل کی پیداوار"),
    "field_production_kg": ("Crop production", "فصل کی پیداوار"),
    "field_yield_kg_ha": ("Yield", "فی ہیکٹر پیداوار"),
    "field_service_ratio": ("Share of canal allowance received", "نہری حصے کا وصول شدہ تناسب"),
    "service_ratio": ("Share of canal allowance received", "نہری حصے کا وصول شدہ تناسب"),
    "field_canal_receipt_m3": ("Canal water received", "وصول شدہ نہری پانی"),
    "field_groundwater_m3": ("Groundwater pumped", "زیر زمین پانی"),
    "groundwater_m3": ("Groundwater pumped", "زیر زمین پانی"),
    "field_cropped_area_ha": ("Cropped area", "کاشت شدہ رقبہ"),
    "capital_commitment_pkr": ("Capital spent", "سرمایہ خرچ"),
    "capital_budget_pkr": ("Capital budget", "سرمایہ بجٹ"),
    "operating_cost_pkr": ("Seasonal operating cost", "موسمی آپریٹنگ لاگت"),
    "canal_source_withdrawal_m3": ("Canal water withdrawn", "نہر سے لیا گیا پانی"),
    "min_service_ratio": ("Lowest field's share of allowance", "کم ترین کھیت کا حصہ"),
    "tail_min_service_ratio": ("Lowest tail field's share", "دم کے کم ترین کھیت کا حصہ"),
    "delta": ("Change", "تبدیلی"),
    "production_delta_kg": ("Change in production", "پیداوار میں تبدیلی"),
    "a": ("Before", "پہلے"),
    "b": ("After", "بعد"),
    "weather": ("Weather", "موسم"),
    "supply": ("Canal supply", "نہری فراہمی"),
    "deliverable": ("Plan deliverable", "منصوبہ قابل عمل"),
    "solver_status": ("Solver status", "حل کی حالت"),
    "dominance": ("Trade-off position", "توازن کی حیثیت"),
    "setting": ("Setting", "ترتیب"),
    "from": ("From", "سے"),
    "to": ("To", "تک"),
    "m3": ("Water volume", "پانی کا حجم"),
    "date": ("Date", "تاریخ"),
    "category": ("Action type", "اقدام کی قسم"),
    "capex_pkr": ("Capital cost", "سرمایہ لاگت"),
    "count": ("Number", "تعداد"),
    "title": ("Step", "قدم"),
    "start_date": ("Start", "آغاز"),
    "commissioning_date": ("Ready by", "تیار ہونے کی تاریخ"),
    "responsible_role": ("Who acts", "ذمہ دار"),
    "required_approval": ("Approval", "منظوری"),
    "fields_affected": ("Fields affected", "متاثرہ کھیت"),
}

HEADLINE_METRICS = (
    "production_kg",
    "capital_commitment_pkr",
    "operating_cost_pkr",
    "canal_source_withdrawal_m3",
    "groundwater_m3",
    "tail_min_service_ratio",
    "min_service_ratio",
    "withdrawal_productivity_kg_m3",
    "cropped_area_ha",
)
FLOW_NAMES = {
    "canal_source": "Canal source",
    "conveyance_loss": "Lost in channels",
    "outlet_receipt": "Delivered to field outlets",
    "pond_fill": "Pond filling",
    "pond_release": "Pond release",
    "pond_losses": "Pond evaporation/seepage",
    "pond_evaporation": "Pond evaporation",
    "pond_seepage": "Pond seepage",
    "pond_spill": "Pond spill",
    "pond_rain": "Rain into ponds",
    "groundwater": "Groundwater pumping",
    "pump_abstraction": "Groundwater pumping",
    "field_application": "Applied on fields",
    "ponds": "Ponds",
    "fields": "Fields",
}


def col(
    key: str,
    kind: str = "number",
    unit: str | None = None,
    *,
    label: str | None = None,
    basis: str | None = None,
    ref: str | None = None,
    unit_column: str | None = None,
) -> Column:
    en, ur = LABELS.get(key, (key.replace("_", " ").capitalize(), None))
    return Column(
        key=key,
        label=label or en,
        label_ur=ur,
        kind=kind,  # type: ignore[arg-type]
        unit=unit,
        unit_column=unit_column,
        basis=basis,  # type: ignore[arg-type]
        ref=ref,  # type: ignore[arg-type]
    )


def basis_of(metric_id: str) -> str:
    from aabflow.copilot.tools.base import metric_basis

    return metric_basis(metric_id)


def field_label(roster: dict[str, dict], fid: str) -> str:
    r = roster.get(fid) or {}
    return r.get("label") or fid.split(":")[-1]


def _group(roster: dict[str, dict], fid: str, fallback: str | None = None) -> str | None:
    return (roster.get(fid) or {}).get("group") or fallback


def _src(tool: str, call_id: str | None, **kw: Iterable[str] | str | None) -> DatasetSource:
    def lst(v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [x for x in v if x]

    return DatasetSource(
        tool=tool,
        call_id=call_id,
        run_ids=lst(kw.get("run_ids")),
        analysis_ids=lst(kw.get("analysis_ids")),
        comparison_ids=lst(kw.get("comparison_ids")),
        revision_ids=lst(kw.get("revision_ids")),
        endpoint=kw.get("endpoint"),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------- run views


def run_metrics(
    ctx: Any, view: dict[str, Any], labels: dict[str, dict], call_id: str | None, tool: str
) -> Dataset | None:
    run = view["run"]
    if run["outcome"] != "plan":
        return None
    rid = run["run_id"]
    by = {m["metric_id"]: m for m in view.get("metrics", []) if m.get("field_id") is None}
    order = [m for m in HEADLINE_METRICS if m in by] + sorted(
        m for m in by if m not in HEADLINE_METRICS
    )
    rows = []
    for mid in order:
        m = by[mid]
        rows.append(
            {
                "metric": (labels.get(mid) or {}).get("label") or mid,
                "metric_id": mid,
                "value": m.get("value"),
                "unit": m.get("unit"),
                "status": m.get("status"),
                "run_id": rid,
            }
        )
    return ctx.datasets.add(
        kind="run_metrics",
        title=f"Key results of {PLAN_NAMES.get(run['plan_kind'], run['plan_kind'])} ({rid})",
        columns=[
            col("metric", "category"),
            col("metric_id", "id"),
            col("value", "number", unit_column="unit"),
            col("unit", "text"),
            col("status", "status"),
            col("run_id", "id", ref="run"),
        ],
        rows=rows,
        charts=["kpi"],
        defaults={"kpi": Encoding(label="metric", value="value", id="run_id", status="status")},
        source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}"),
        basis=sorted({basis_of(r["metric_id"]) for r in rows}),
        notes=[
            (
                "Production and yields are AquaCrop crop-model outputs (uncalibrated unless stated); "
                "costs use configured assumptions."
            )
        ],
    )


FIELD_METRICS = (
    ("field_production_kg", "kg"),
    ("field_yield_kg_ha", "kg/ha"),
    ("field_service_ratio", "ratio"),
    ("field_canal_receipt_m3", "m3"),
    ("field_groundwater_m3", "m3"),
    ("field_cropped_area_ha", "ha"),
)


def field_outcomes(
    ctx: Any, view: dict[str, Any], roster: dict[str, dict], call_id: str | None, tool: str
) -> Dataset | None:
    run = view["run"]
    if run["outcome"] != "plan":
        return None
    rid = run["run_id"]
    per: dict[str, dict[str, Any]] = {}
    units: dict[str, str] = {}
    for m in view.get("metrics", []):
        fid = m.get("field_id")
        if not fid:
            continue
        per.setdefault(fid, {})[m["metric_id"]] = m.get("value")
        if m.get("unit"):
            units[m["metric_id"]] = m["unit"]
    if not per:
        return None
    rows = []
    for fid in sorted(per, key=lambda f: field_label(roster, f)):
        r = {
            "field": field_label(roster, fid),
            "field_id": fid,
            "group": _group(roster, fid),
            "run_id": rid,
        }
        for mid, _ in FIELD_METRICS:
            r[mid] = per[fid].get(mid)
        rows.append(r)
    cols = [
        col("field", "category"),
        col("field_id", "id", ref="field"),
        col("group", "category"),
    ]
    for mid, unit in FIELD_METRICS:
        cols.append(col(mid, "number", units.get(mid, unit), basis=basis_of(mid)))
    cols.append(col("run_id", "id", ref="run"))
    return ctx.datasets.add(
        kind="field_outcomes",
        title=f"Field-by-field results of {PLAN_NAMES.get(run['plan_kind'], run['plan_kind'])} ({rid})",
        columns=cols,
        rows=rows,
        charts=["bar", "map", "scatter"],
        defaults={
            "bar": Encoding(x="field", y=["field_production_kg"], color="group", id="field_id"),
            "map": Encoding(id="field_id", value="field_service_ratio", label="field"),
            "scatter": Encoding(
                x="field_service_ratio", y=["field_yield_kg_ha"], color="group", id="field_id"
            ),
            "*": Encoding(x="field", y=["field_production_kg"], id="field_id"),
        },
        source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}"),
        basis=["model_output", "computed_from_inputs"],
        notes=[
            "Service ratio = canal water received / the field's fixed reference allowance (assumed rights)."
        ],
    )


# ------------------------------------------------------------------ comparisons


PLAN_COLUMNS = (
    ("production_kg", "kg"),
    ("capital_commitment_pkr", "PKR"),
    ("operating_cost_pkr", "PKR"),
    ("canal_source_withdrawal_m3", "m3"),
    ("groundwater_m3", "m3"),
    ("min_service_ratio", "ratio"),
    ("tail_min_service_ratio", "ratio"),
)


def plans_side_by_side(
    ctx: Any,
    cmp: dict[str, Any],
    labels_by_run: dict[str, str],
    call_id: str | None,
    tool: str,
    extra_views: list[dict[str, Any]] | None = None,
) -> Dataset:
    """One row per compared run, values copied from the comparison's run-level a/b values.

    ``extra_views``: run views shown alongside but outside the matched comparison (the robust plan R is
    evaluated across uncertain states, so it is labelled non-matched); their values come from the run."""
    run_ids = cmp["run_ids"]
    plans = {p["run_id"]: p for p in cmp["plans"]}
    vals: dict[str, dict[str, Any]] = {r: {} for r in run_ids}
    units: dict[str, str] = {}
    for d in cmp["deltas"]:
        if d.get("field_id") is not None:
            continue
        units[d["metric_id"]] = d.get("unit")
        if d.get("a_run_id") in vals:
            vals[d["a_run_id"]].setdefault(d["metric_id"], d.get("a"))
        if d.get("b_run_id") in vals:
            vals[d["b_run_id"]].setdefault(d["metric_id"], d.get("b"))
    rows = []
    for r in run_ids:
        p = plans.get(r, {})
        row = {
            "plan": labels_by_run.get(r) or PLAN_NAMES.get(p.get("plan_kind"), r),
            "plan_kind": p.get("plan_kind"),
            "solver_status": p.get("solver_status"),
            "run_id": r,
        }
        for mid, _ in PLAN_COLUMNS:
            row[mid] = vals[r].get(mid) if p.get("outcome", "plan") == "plan" else None
        rows.append(row)
    extra_notes = []
    for view in extra_views or []:
        run = view["run"]
        by = {m["metric_id"]: m for m in view.get("metrics", []) if m.get("field_id") is None}
        row = {
            "plan": labels_by_run.get(run["run_id"])
            or PLAN_NAMES.get(run["plan_kind"], run["run_id"]),
            "plan_kind": run["plan_kind"],
            "solver_status": run["solver_status"],
            "run_id": run["run_id"],
        }
        for mid, _ in PLAN_COLUMNS:
            row[mid] = (by.get(mid) or {}).get("value") if run["outcome"] == "plan" else None
        rows.append(row)
        extra_notes.append(
            f"{row['plan']} is evaluated across several weather/supply states; it is shown for reference and "
            "is not part of the matched comparison."
        )
    cols = [col("plan", "category"), col("plan_kind", "category")]
    for mid, unit in PLAN_COLUMNS:
        cols.append(col(mid, "number", units.get(mid) or unit, basis=basis_of(mid)))
    cols += [col("solver_status", "status"), col("run_id", "id", ref="run")]
    return ctx.datasets.add(
        kind="plans_side_by_side",
        title="Plans side by side",
        columns=cols,
        rows=rows,
        charts=["bar", "grouped_bar", "kpi"],
        defaults={
            "bar": Encoding(x="plan", y=["production_kg"], id="run_id", status="solver_status"),
            "grouped_bar": Encoding(
                x="plan", y=["min_service_ratio", "tail_min_service_ratio"], id="run_id"
            ),
            "kpi": Encoding(label="plan", value="production_kg", id="run_id"),
        },
        source=_src(
            tool,
            call_id,
            run_ids=[r["run_id"] for r in rows],
            comparison_ids=cmp["comparison_id"],
            endpoint="/comparisons",
        ),
        basis=["model_output", "computed_from_inputs"],
        notes=[cmp["labels"]["comparison"], *extra_notes]
        + (
            []
            if cmp["compatible"]
            else [
                "NON-MATCHED comparison: conditions differ, so differences are not caused by the plan."
            ]
        ),
    )


def field_deltas(
    ctx: Any,
    cmp: dict[str, Any],
    roster: dict[str, dict],
    call_id: str | None,
    tool: str,
    metric_id: str = "field_production_kg",
    pair: tuple[str, str] | None = None,
) -> Dataset | None:
    """Per-field server-computed deltas between two compared runs (default: first and last)."""
    a_id, b_id = pair or (cmp["run_ids"][0], cmp["run_ids"][-1])
    rows = []
    unit = None
    for d in cmp["deltas"]:
        if (
            d.get("field_id")
            and d["metric_id"] == metric_id
            and d.get("a_run_id") == a_id
            and d.get("b_run_id") == b_id
        ):
            unit = d.get("unit")
            fid = d["field_id"]
            rows.append(
                {
                    "field": field_label(roster, fid),
                    "field_id": fid,
                    "group": _group(roster, fid),
                    "a": d.get("a"),
                    "b": d.get("b"),
                    "delta": d.get("delta"),
                    "status": d.get("status"),
                }
            )
    if not rows:
        return None
    rows.sort(key=lambda r: field_label(roster, r["field_id"]))
    plans = {p["run_id"]: p.get("plan_kind") for p in cmp["plans"]}
    an, bn = PLAN_NAMES.get(plans.get(a_id), a_id), PLAN_NAMES.get(plans.get(b_id), b_id)
    return ctx.datasets.add(
        kind="field_deltas",
        title=f"Change per field: {bn} versus {an}",
        columns=[
            col("field", "category"),
            col("field_id", "id", ref="field"),
            col("group", "category"),
            col("a", "number", unit, label=f"{an}", basis=basis_of(metric_id)),
            col("b", "number", unit, label=f"{bn}", basis=basis_of(metric_id)),
            col(
                "delta",
                "number",
                unit,
                label="Change (after minus before)",
                basis=basis_of(metric_id),
            ),
            col("status", "status"),
        ],
        rows=rows,
        charts=["delta_bar", "map", "bar"],
        defaults={
            "delta_bar": Encoding(x="field", y=["delta"], color="group", id="field_id"),
            "map": Encoding(id="field_id", value="delta", label="field"),
            "bar": Encoding(x="field", y=["a", "b"], id="field_id"),
        },
        source=_src(
            tool,
            call_id,
            run_ids=[a_id, b_id],
            comparison_ids=cmp["comparison_id"],
            endpoint="/comparisons",
        ),
        basis=[basis_of(metric_id)],
        notes=[f"Metric {metric_id}; deltas are computed by the comparison service (b minus a)."]
        + ([] if cmp["compatible"] else ["NON-MATCHED: not attributable to the plan."]),
    )


def incremental_steps(
    ctx: Any, cmp: dict[str, Any], call_id: str | None, tool: str
) -> Dataset | None:
    steps = cmp.get("incremental") or []
    if not steps:
        return None
    rows = [
        {
            "step": s["step"],
            "production_kg": s.get("production_kg"),
            "capital_commitment_pkr": s.get("capital_commitment_pkr"),
            "operating_cost_pkr": s.get("operating_cost_pkr"),
            "groundwater_m3": s.get("groundwater_m3"),
            "min_service_ratio": s.get("min_service_ratio"),
            "note": s.get("note"),
            "run_id": s.get("to_run_id"),
        }
        for s in steps
    ]
    return ctx.datasets.add(
        kind="ladder_steps",
        title="What each step up the plan ladder adds",
        columns=[
            col("step", "category", label="Step"),
            col("production_kg", "number", "kg", label="Extra production", basis="model_output"),
            col("capital_commitment_pkr", "number", "PKR", label="Extra capital"),
            col("operating_cost_pkr", "number", "PKR", label="Extra operating cost"),
            col("groundwater_m3", "number", "m3", label="Extra groundwater"),
            col("min_service_ratio", "number", "ratio", label="Change in lowest field share"),
            col("note", "text", label="Note"),
            col("run_id", "id", ref="run"),
        ],
        rows=rows,
        charts=["delta_bar", "bar"],
        defaults={"*": Encoding(x="step", y=["production_kg"], id="run_id")},
        source=_src(
            tool,
            call_id,
            run_ids=cmp["run_ids"],
            comparison_ids=cmp["comparison_id"],
            endpoint="/comparisons",
        ),
        basis=["model_output", "computed_from_inputs"],
        notes=["Increments are computed by the comparison service between consecutive plans."],
    )


# --------------------------------------------------------------------- analyses


def _setting_label(s: dict[str, Any]) -> str:
    cap = s.get("capital_budget_pkr")
    txt = f"PKR {cap:,.0f}" if isinstance(cap, int | float) else "budget ?"
    if s.get("minimum_service_ratio") is not None:
        txt += f", {s.get('service_group') or 'all'} floor {s['minimum_service_ratio']:.2f}"
    return txt


def frontier(ctx: Any, a: dict[str, Any], call_id: str | None, tool: str) -> Dataset | None:
    res = a.get("result") or {}
    pts = res.get("points") or []
    if not pts:
        return None
    rows = []
    for p in pts:
        rows.append(
            {
                "point": p.get("point_id"),
                "setting": _setting_label(p.get("setting") or {}),
                "capital_budget_pkr": (p.get("setting") or {}).get("capital_budget_pkr"),
                "capital_commitment_pkr": p.get("capital_commitment_pkr"),
                "production_kg": p.get("production_kg"),
                "tail_min_service_ratio": p.get("tail_min_service_ratio"),
                "min_service_ratio": p.get("min_service_ratio"),
                "groundwater_m3": p.get("groundwater_m3"),
                "solver_status": p.get("solver_status"),
                "dominance": p.get("dominance"),
                "run_id": p.get("run_id"),
            }
        )
    return ctx.datasets.add(
        kind="frontier",
        title="Spending versus production (each point is a solved plan)",
        columns=[
            col("point", "id", label="Point"),
            col("setting", "category"),
            col("capital_budget_pkr", "number", "PKR"),
            col("capital_commitment_pkr", "number", "PKR"),
            col("production_kg", "number", "kg", basis="model_output"),
            col("tail_min_service_ratio", "number", "ratio"),
            col("min_service_ratio", "number", "ratio"),
            col("groundwater_m3", "number", "m3"),
            col("solver_status", "status"),
            col("dominance", "status"),
            col("run_id", "id", ref="run"),
        ],
        rows=rows,
        charts=["frontier", "scatter", "bar"],
        defaults={
            "frontier": Encoding(
                x="capital_commitment_pkr",
                y=["production_kg"],
                color="dominance",
                id="run_id",
                label="setting",
                status="solver_status",
            ),
            "scatter": Encoding(
                x="tail_min_service_ratio", y=["production_kg"], color="dominance", id="run_id"
            ),
            "bar": Encoding(x="setting", y=["production_kg"], id="run_id", status="solver_status"),
        },
        source=_src(
            tool,
            call_id,
            analysis_ids=a.get("analysis_id"),
            run_ids=[r["run_id"] for r in rows],
            revision_ids=a.get("base_revision_id"),
            endpoint=f"/analyses/{a.get('analysis_id')}",
        ),
        basis=["model_output", "solver_result"],
        notes=[
            res.get("label") or "Nondominated among evaluated plans",
            "Points without production are infeasible/unknown settings: no plan exists for them.",
        ],
    )


def stress(ctx: Any, a: dict[str, Any], call_id: str | None, tool: str) -> Dataset | None:
    res = a.get("result") or {}
    cells = res.get("cells") or []
    if not cells:
        return None
    rows = []
    for c in cells:
        deliverable = c.get("deliverable")
        rows.append(
            {
                "weather": c.get("weather_scenario_id"),
                "supply": c.get("supply_label") or c.get("supply_profile_id"),
                "state_id": c.get("state_id"),
                "production_kg": c.get("production_kg") if deliverable else None,
                "deliverable": bool(deliverable),
                "status": "deliverable" if deliverable else "undeliverable",
                "violations": len(c.get("violations") or []),
                "solver_status": c.get("solver_status"),
                "run_id": c.get("run_id"),
            }
        )
    mode = res.get("mode") or (a.get("request") or {}).get("mode")
    return ctx.datasets.add(
        kind="stress_matrix",
        title=f"Stress test ({'same plan in every condition' if mode == 'fixed_plan' else 'recovery plans'})",
        columns=[
            col("weather", "category"),
            col("supply", "category"),
            col("state_id", "id", label="State"),
            col("production_kg", "number", "kg", basis="model_output"),
            col("deliverable", "bool"),
            col("status", "status"),
            col("violations", "number", "count", label="Broken delivery rules"),
            col("solver_status", "status"),
            col("run_id", "id", ref="run"),
        ],
        rows=rows,
        charts=["heatmap", "bar"],
        defaults={
            "heatmap": Encoding(
                x="supply", y=["weather"], value="production_kg", status="status", id="run_id"
            ),
            "bar": Encoding(x="state_id", y=["production_kg"], status="status", id="run_id"),
        },
        source=_src(
            tool,
            call_id,
            analysis_ids=a.get("analysis_id"),
            run_ids=[res.get("run_id")] + [r["run_id"] for r in rows],
            endpoint=f"/analyses/{a.get('analysis_id')}",
        ),
        basis=["model_output", "solver_result"],
        notes=[
            (
                "Undeliverable cells have no production: the plan's dated deliveries break the rules in "
                "that condition (not a low yield)."
            ),
            res.get("worst_case_scope") or "Worst case means worst within the tested states only.",
        ],
    )


def analysis_points(ctx: Any, a: dict[str, Any], call_id: str | None, tool: str) -> Dataset | None:
    """Sensitivity points, synergy arms or why-not base/alternative as one table of solved runs."""
    res = a.get("result") or {}
    kind = a.get("kind")
    rows: list[dict[str, Any]] = []
    if kind == "sensitivity":
        for p in res.get("points") or []:
            rows.append(
                {
                    "label": f"{res.get('parameter')} = {p.get('value')}",
                    "x": p.get("value"),
                    **_pt(p),
                }
            )
    elif kind == "synergy":
        names = {"none": "Neither", "a": "Only A", "b": "Only B", "ab": "Both"}
        for k in ("none", "a", "b", "ab"):
            p = (res.get("arms") or {}).get(k)
            if p:
                rows.append({"label": names[k], "x": None, **_pt(p)})
    elif kind == "why_not":
        for k, name in (("base", "Base plan"), ("alternative", "Alternative")):
            p = res.get(k)
            if isinstance(p, dict):
                rows.append({"label": name, "x": None, **_pt(p)})
    if not rows:
        return None
    charts = ["bar"] + (["line"] if kind == "sensitivity" else [])
    defaults = {
        "bar": Encoding(x="label", y=["production_kg"], id="run_id", status="solver_status"),
        "line": Encoding(x="x", y=["production_kg"], id="run_id"),
    }
    return ctx.datasets.add(
        kind=f"{kind}_points",
        title={
            "sensitivity": "How the result changes across the tested values",
            "synergy": "Each action alone and together",
            "why_not": "Base plan versus the alternative",
        }.get(kind or "", "Solved runs"),
        columns=[
            col("label", "category", label="Case"),
            col("x", "number", None, label=str(res.get("parameter") or "value")),
            col("production_kg", "number", "kg", basis="model_output"),
            col("capital_commitment_pkr", "number", "PKR"),
            col("operating_cost_pkr", "number", "PKR"),
            col("min_service_ratio", "number", "ratio"),
            col("solver_status", "status"),
            col("run_id", "id", ref="run"),
        ],
        rows=rows,
        charts=charts,
        defaults=defaults,
        source=_src(
            tool,
            call_id,
            analysis_ids=a.get("analysis_id"),
            run_ids=[r["run_id"] for r in rows if r.get("run_id")],
            endpoint=f"/analyses/{a.get('analysis_id')}",
        ),
        basis=["model_output", "solver_result"],
        notes=["Rows without production have no feasible plan (infeasible/unknown/rejected)."],
    )


def _pt(p: dict[str, Any]) -> dict[str, Any]:
    ok = p.get("outcome") == "plan"
    return {
        "production_kg": p.get("production_kg") if ok else None,
        "capital_commitment_pkr": p.get("capital_commitment_pkr") if ok else None,
        "operating_cost_pkr": p.get("operating_cost_pkr") if ok else None,
        "min_service_ratio": p.get("min_service_ratio") if ok else None,
        "solver_status": p.get("solver_status") or p.get("outcome"),
        "run_id": p.get("run_id"),
    }


def for_analysis(ctx: Any, a: dict[str, Any], call_id: str | None, tool: str) -> list[Dataset]:
    kind = a.get("kind")
    out: list[Dataset | None] = []
    if kind == "frontier":
        out.append(frontier(ctx, a, call_id, tool))
    elif kind == "stress":
        out.append(stress(ctx, a, call_id, tool))
    elif kind in ("sensitivity", "synergy", "why_not"):
        out.append(analysis_points(ctx, a, call_id, tool))
    return [d for d in out if d is not None]


# ---------------------------------------------------------- impact / economics


def water_flows(
    ctx: Any, acc: dict[str, Any], roster: dict[str, dict], call_id: str | None, tool: str
) -> list[Dataset]:
    if not acc.get("available"):
        return []
    rid = acc["run_id"]
    out = []
    flows = [
        {
            "from": FLOW_NAMES.get(f["from"], f["from"]),
            "to": FLOW_NAMES.get(f["to"], f["to"]),
            "m3": f.get("m3"),
        }
        for f in acc.get("flows") or []
        if isinstance(f.get("m3"), int | float) and f["m3"] > 0
    ]
    if flows:
        out.append(
            ctx.datasets.add(
                kind="water_flows",
                title=f"Where the water goes (run {rid})",
                columns=[col("from", "category"), col("to", "category"), col("m3", "number", "m3")],
                rows=flows,
                charts=["sankey"],
                defaults={"sankey": Encoding(source="from", target="to", value="m3")},
                source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/accounting"),
                basis=["computed_from_inputs"],
                notes=[
                    (acc.get("reconciliation") or {}).get("note")
                    or "Ledger flows in the typical state."
                ],
            )
        )
    pf = acc.get("per_field") or {}
    if pf:
        rows = [
            {
                "field": field_label(roster, fid),
                "field_id": fid,
                "group": _group(roster, fid),
                "canal_m3": v.get("outlet_receipt"),
                "pump_m3": v.get("pump_abstraction"),
                "pond_m3": v.get("pond_release"),
                "applied_m3": v.get("field_application"),
            }
            for fid, v in sorted(pf.items(), key=lambda kv: field_label(roster, kv[0]))
        ]
        out.append(
            ctx.datasets.add(
                kind="water_by_field",
                title=f"Water sources per field (run {rid})",
                columns=[
                    col("field", "category"),
                    col("field_id", "id", ref="field"),
                    col("group", "category"),
                    col("canal_m3", "number", "m3", label="Canal water"),
                    col("pump_m3", "number", "m3", label="Groundwater pumped"),
                    col("pond_m3", "number", "m3", label="From ponds"),
                    col("applied_m3", "number", "m3", label="Applied on field"),
                ],
                rows=rows,
                charts=["stacked_bar", "map"],
                defaults={
                    "stacked_bar": Encoding(
                        x="field", y=["canal_m3", "pump_m3", "pond_m3"], id="field_id"
                    ),
                    "map": Encoding(id="field_id", value="pump_m3", label="field"),
                },
                source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/accounting"),
                basis=["computed_from_inputs"],
                notes=["A missing source means the field did not use it (no ledger event)."],
            )
        )
    return out


def economics(ctx: Any, eco: dict[str, Any], call_id: str | None, tool: str) -> list[Dataset]:
    if not eco.get("available"):
        return []
    rid = eco["run_id"]
    out = []
    cards = [
        ("Total project cost", eco.get("gross_project_cost_pkr"), "PKR", "available"),
        ("Capital budget", eco.get("capital_budget_pkr"), "PKR", "available"),
        ("Paid by participants (assumed)", eco.get("participant_cash_pkr"), "PKR", "available"),
        ("Seasonal operating cost", eco.get("seasonal_operating_pkr"), "PKR", "available"),
        ("Operating budget", eco.get("operating_budget_pkr"), "PKR", "available"),
    ]
    for key in ("crop_value", "irrigation_contribution"):
        m = eco.get(key) or {}
        cards.append(
            (
                {"crop_value": "Crop value", "irrigation_contribution": "Irrigation contribution"}[
                    key
                ],
                m.get("value"),
                m.get("unit") or "PKR",
                m.get("status") or "not_estimated",
            )
        )
    out.append(
        ctx.datasets.add(
            kind="money_cards",
            title=f"Money summary (run {rid})",
            columns=[
                col("metric", "category"),
                col("value", "number", unit_column="unit"),
                col("unit", "text"),
                col("status", "status"),
            ],
            rows=[{"metric": a, "value": b, "unit": c, "status": d} for a, b, c, d in cards],
            charts=["kpi"],
            defaults={"kpi": Encoding(label="metric", value="value", status="status")},
            source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/economics"),
            basis=["assumption", "computed_from_inputs"],
            notes=["Costs are configured assumptions unless an evidence record says otherwise."]
            + [
                f"{k}: {(eco.get(k) or {}).get('reason')}"
                for k in ("crop_value", "public_grant_pkr", "cashflow")
                if (eco.get(k) or {}).get("reason")
            ],
        )
    )
    by_cat: dict[str, dict[str, Any]] = {}
    for i in eco.get("instances") or []:
        c = by_cat.setdefault(
            i["category"], {"category": i["category"], "count": 0, "capex_pkr": 0.0}
        )
        c["count"] += 1
        c["capex_pkr"] += float(i.get("capex_pkr") or 0)
    if by_cat:
        out.append(
            ctx.datasets.add(
                kind="cost_by_category",
                title=f"Where the capital goes (run {rid})",
                columns=[
                    col("category", "category"),
                    col("count", "number", "count"),
                    col("capex_pkr", "number", "PKR"),
                ],
                rows=sorted(by_cat.values(), key=lambda r: -r["capex_pkr"]),
                charts=["bar"],
                defaults={"bar": Encoding(x="category", y=["capex_pkr"])},
                source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/economics"),
                basis=["assumption"],
                notes=[
                    "Server-side sum of the listed selected investments per category; shared repairs counted once."
                ],
            )
        )
    return out


def equity(
    ctx: Any, eq: dict[str, Any], roster: dict[str, dict], call_id: str | None, tool: str
) -> list[Dataset]:
    if not eq.get("available"):
        return []
    rid, bid = eq["run_id"], eq.get("baseline_run_id")
    share = eq.get("pumping_burden_share") or {}
    rows = [
        {
            "field": field_label(roster, f["field_id"]),
            "field_id": f["field_id"],
            "group": f.get("group"),
            "service_ratio": f.get("service_ratio"),
            "production_kg": f.get("production_kg"),
            "production_delta_kg": f.get("production_delta_kg"),
            "groundwater_m3": f.get("groundwater_m3"),
            "pumping_share": share.get(f["field_id"]),
            "worse_off": f["field_id"] in (eq.get("fields_worse_off") or []),
        }
        for f in eq.get("fields") or []
    ]
    rows.sort(key=lambda r: r["field"])
    out = [
        ctx.datasets.add(
            kind="equity_fields",
            title=f"Who gets what (run {rid}{f' vs {bid}' if bid else ''})",
            columns=[
                col("field", "category"),
                col("field_id", "id", ref="field"),
                col("group", "category"),
                col("service_ratio", "number", "ratio"),
                col("production_kg", "number", "kg", basis="model_output"),
                col(
                    "production_delta_kg",
                    "number",
                    "kg",
                    label="Change versus baseline",
                    basis="model_output",
                ),
                col("groundwater_m3", "number", "m3"),
                col("pumping_share", "number", "ratio", label="Share of pumping burden"),
                col("worse_off", "bool", label="Worse off than baseline"),
            ],
            rows=rows,
            charts=["bar", "delta_bar", "map"],
            defaults={
                "bar": Encoding(x="field", y=["service_ratio"], color="group", id="field_id"),
                "delta_bar": Encoding(
                    x="field", y=["production_delta_kg"], color="group", id="field_id"
                ),
                "map": Encoding(id="field_id", value="service_ratio", label="field"),
            },
            source=_src(tool, call_id, run_ids=[rid, bid], endpoint=f"/runs/{rid}/equity"),
            basis=["model_output", "computed_from_inputs", "assumption"],
            notes=[
                f"Service = {eq.get('measure_label') or 'receipt / reference allowance'} (rights are assumed).",
                eq.get("owner_note") or "",
            ],
        )
    ]
    groups = eq.get("groups") or {}
    if groups:
        out.append(
            ctx.datasets.add(
                kind="equity_groups",
                title=f"Head, middle and tail fields (run {rid})",
                columns=[
                    col("group", "category"),
                    col("fields", "number", "count", label="Fields"),
                    col("mean_service_ratio", "number", "ratio", label="Average share received"),
                    col("min_service_ratio", "number", "ratio", label="Lowest share received"),
                ],
                rows=[
                    {
                        "group": g,
                        "fields": v.get("fields"),
                        "mean_service_ratio": v.get("mean_service_ratio"),
                        "min_service_ratio": v.get("min_service_ratio"),
                    }
                    for g, v in groups.items()
                ],
                charts=["grouped_bar", "bar"],
                defaults={"*": Encoding(x="group", y=["mean_service_ratio", "min_service_ratio"])},
                source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/equity"),
                basis=["computed_from_inputs", "assumption"],
                notes=[
                    "Shares are canal receipt divided by each field's assumed reference allowance."
                ],
            )
        )
    return out


def impact_cards(ctx: Any, imp: dict[str, Any], call_id: str | None, tool: str) -> list[Dataset]:
    if not imp.get("available"):
        return []
    rid = imp["run_id"]
    rows = []
    for c in imp.get("cards") or []:
        head = next(iter(c.get("values") or []), {}) or {}
        rows.append(
            {
                "card": c.get("card"),
                "interpretation": c.get("interpretation"),
                "metric_id": head.get("metric_id"),
                "value": head.get("value"),
                "unit": head.get("unit"),
                "status": c.get("status"),
                "reason": c.get("reason"),
            }
        )
    out = [
        ctx.datasets.add(
            kind="sdg_cards",
            title=f"Sustainable Development Goal proxies (run {rid})",
            columns=[
                col("card", "category", label="SDG card"),
                col("interpretation", "text", label="What it means"),
                col("metric_id", "id"),
                col("value", "number", unit_column="unit"),
                col("unit", "text"),
                col("status", "status"),
                col("reason", "text", label="Why not available"),
            ],
            rows=rows,
            charts=["kpi"],
            defaults={"kpi": Encoding(label="card", value="value", status="status")},
            source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/impact"),
            basis=["model_output", "computed_from_inputs"],
            notes=["Proxies, not official UN indicator scores; no 0-100 SDG score is computed."],
        )
    ]
    return out


def action_steps(ctx: Any, ap: dict[str, Any], call_id: str | None, tool: str) -> list[Dataset]:
    if not ap.get("available"):
        return []
    rid = ap["run_id"]
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for a in ap.get("actions") or []:
        cat = a["category"]
        key = (cat, a.get("start_date") or "")
        if cat in ("leveling",):
            key = (cat, "")
        g = groups.setdefault(
            key,
            {
                "category": cat,
                "start_date": a.get("start_date"),
                "commissioning_date": a.get("commissioning_date"),
                "capex_pkr": 0.0,
                "count": 0,
                "fields": set(),
                "targets": [],
                "responsible_role": a.get("responsible_role"),
                "required_approval": a.get("required_approval"),
            },
        )
        g["capex_pkr"] += float(a.get("capex_pkr") or 0)
        g["count"] += 1
        g["fields"].update(a.get("affected_fields") or [])
        g["targets"] += a.get("target_ids") or []
        for k, pick in (("start_date", min), ("commissioning_date", max)):
            if a.get(k) and g.get(k):
                g[k] = pick(g[k], a[k])
    nice = {
        "shared_repair": "Repair shared watercourse",
        "leveling": "Level fields",
        "pond": "Build farm pond",
        "pump_supplement": "Use existing pump",
        "operational": "Adjust irrigation timing",
    }
    rows = []
    for g in sorted(groups.values(), key=lambda g: g.get("start_date") or ""):
        tgt = ", ".join(t.split(":")[-1] for t in g["targets"][:3])
        more = f" +{len(g['targets']) - 3} more" if len(g["targets"]) > 3 else ""
        rows.append(
            {
                "title": f"{nice.get(g['category'], g['category'].replace('_', ' ').title())}"
                + (f" ({g['count']})" if g["count"] > 1 else "")
                + (f": {tgt}{more}" if tgt else ""),
                "category": g["category"],
                "start_date": g.get("start_date"),
                "commissioning_date": g.get("commissioning_date"),
                "capex_pkr": g["capex_pkr"],
                "fields_affected": len(g["fields"]),
                "responsible_role": g.get("responsible_role"),
                "required_approval": g.get("required_approval"),
                "run_id": rid,
            }
        )
    out = [
        ctx.datasets.add(
            kind="action_steps",
            title=f"What to do, in order (run {rid})",
            columns=[
                col("title", "text"),
                col("category", "category"),
                col("start_date", "date"),
                col("commissioning_date", "date"),
                col("capex_pkr", "number", "PKR"),
                col("fields_affected", "number", "count"),
                col("responsible_role", "text"),
                col("required_approval", "text"),
                col("run_id", "id", ref="run"),
            ],
            rows=rows,
            charts=["steps"],
            defaults={
                "steps": Encoding(label="title", x="start_date", value="capex_pkr", id="run_id")
            },
            source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/action-plan"),
            basis=["assumption", "solver_result"],
            notes=[
                ap.get("status_note") or "",
                "Steps group the run's selected actions by type; costs are server-side sums of listed actions.",
                "A recommendation does not operate a canal, order equipment or contact a farmer.",
            ],
        )
    ]
    return out


def timeline(
    ctx: Any, tl: dict[str, Any], roster: dict[str, dict], call_id: str | None, tool: str
) -> Dataset | None:
    dates = tl.get("dates") or []
    series = tl.get("series") or []
    if not dates or not series:
        return None
    keep = [
        s
        for s in series
        if s["series_id"]
        in (
            "canal_receipt_m3",
            "pump_m3",
            "pond_release_m3",
            "field_application_m3",
            "gross_irrigation_mm",
            "precipitation_mm",
            "et_mm",
            "root_zone_water_mm",
            "canopy_fraction",
            "biomass_kg_ha",
        )
    ] or series[:8]
    rows = []
    for i, d in enumerate(dates):
        r = {"date": d}
        for s in keep:
            r[s["series_id"]] = s["values"][i] if i < len(s["values"]) else None
        rows.append(r)
    fid = tl.get("field_id")
    cols = [col("date", "date")] + [
        col(
            s["series_id"],
            "number",
            s.get("unit"),
            label=s.get("label"),
            basis="model_output" if s.get("source") == "crop_model" else "computed_from_inputs",
        )
        for s in keep
    ]
    ids = [s["series_id"] for s in keep]
    water = [x for x in ("canal_receipt_m3", "pump_m3", "pond_release_m3") if x in ids] or ids[:1]
    crop = [x for x in ("canopy_fraction",) if x in ids] or ids[:1]
    return ctx.datasets.add(
        kind="timeline",
        title=f"Season timeline for {field_label(roster, fid) if fid else 'the network'} "
        f"({tl.get('resolution')}, run {tl['run_id']})",
        columns=cols,
        rows=rows,
        charts=["line", "area", "bar"],
        defaults={
            "line": Encoding(x="date", y=crop),
            "area": Encoding(x="date", y=water),
            "bar": Encoding(x="date", y=water),
        },
        source=_src(tool, call_id, run_ids=tl["run_id"], endpoint=f"/runs/{tl['run_id']}/timeline"),
        basis=["model_output", "computed_from_inputs"],
        notes=[tl.get("note") or "Missing values are gaps, not zeros."],
    )


def decisions(ctx: Any, ex: dict[str, Any], call_id: str | None, tool: str) -> Dataset | None:
    rows = []
    for s in ex.get("selected") or []:
        rows.append(
            {
                "instance_id": s["instance_id"],
                "category": s.get("category"),
                "capex_pkr": s.get("capex_pkr"),
                "decision": "selected",
                "why": "; ".join(s.get("why") or [])[:240],
            }
        )
    for s in ex.get("rejected") or []:
        rows.append(
            {
                "instance_id": s["instance_id"],
                "category": s.get("category"),
                "capex_pkr": s.get("capex_pkr"),
                "decision": s.get("kind") or "not_selected",
                "why": "; ".join(s.get("why") or [])[:240],
            }
        )
    if not rows:
        return None
    rid = ex.get("run_id")
    return ctx.datasets.add(
        kind="decisions",
        title=f"Which investments were chosen and why (run {rid})",
        columns=[
            col("instance_id", "id", ref="instance", label="Investment"),
            col("category", "category"),
            col("capex_pkr", "number", "PKR"),
            col("decision", "status", label="Decision"),
            col("why", "text", label="Reason"),
        ],
        rows=rows,
        charts=["table"],
        defaults={},
        source=_src(tool, call_id, run_ids=rid, endpoint=f"/runs/{rid}/explanations"),
        basis=["solver_result", "assumption"],
        notes=[
            "Reasons are the service's deterministic explanations within the finite candidate library."
        ],
    )
