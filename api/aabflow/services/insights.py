"""Run-derived views from the same metric registry: comparisons with compatibility
certificates (AT08), water accounting (F15), equity (F15), economics and action
plan (F14), and SDG/impact proxies (F16). Nothing here recomputes crop yield; all
values come from a run's stored MetricValues, selection and ledger.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from aabflow.api.errors import invalid
from aabflow.domain.calendar import local_crop_date
from aabflow.domain.hashes import content_hash
from aabflow.domain.ids import new_id
from aabflow.domain.schemas import MetricStatus, MetricValue
from aabflow.repositories.sqlite import dumps, loads, tx, utcnow
from aabflow.services.metrics import METRICS_VERSION, REGISTRY, mv
from aabflow.services.pilots import PilotRepository
from aabflow.services.runs import LoadedRun, load_run

QUANTUM_KG = 0.1


def _mindex(run: LoadedRun) -> dict[tuple[str, str | None], MetricValue]:
    return {(m.metric_id, m.field_id): m for m in run.metrics()}


def _conditions(run: LoadedRun) -> dict[str, Any]:
    meta = run.meta
    c = dict(meta.get("compatibility") or {})
    c["candidate_library_hash"] = run.result.candidate_library_hash
    return c


CAUSAL_KEYS = (
    "pilot_id",
    "pilot_version",
    "season_id",
    "states",
    "typical_state",
    "uniform_reduction_fraction",
    "blocked_edge_ids",
    "metrics_version",
    "initial_state",
)
TREATMENT_LABELS = {
    "capital_budget_pkr": "capital budget",
    "operating_budget_pkr": "operating budget",
    "minimum_service_ratio": "service floor",
    "service_group": "service group",
    "allowed_intervention_instance_ids": "allowed interventions",
    "forced_instance_ids": "forced interventions",
    "excluded_instance_ids": "excluded interventions",
    "permit_groundwater": "groundwater permission",
    "optimization_mode": "optimization mode",
}


def certificate(runs: list[LoadedRun]) -> dict[str, Any]:
    conds = [_conditions(r) for r in runs]
    shared, differences = [], []
    for k in CAUSAL_KEYS:
        vals = [c.get(k) for c in conds]
        if all(v == vals[0] for v in vals):
            shared.append({"condition": k, "value": vals[0]})
        else:
            differences.append(
                {
                    "condition": k,
                    "values": vals,
                    "kind": "non_causal",
                    "note": "conditions differ; deltas are not attributable to the plan",
                }
            )
    libs = [c.get("candidate_library_hash") for c in conds]
    if len(set(libs)) > 1:
        differences.append(
            {
                "condition": "candidate_library_hash",
                "values": libs,
                "kind": "approximation",
                "note": "different candidate libraries (finite option sets) were searched",
            }
        )
    reqs = [r.json("scenario.json")["request"] for r in runs]
    for k, label in TREATMENT_LABELS.items():
        vals = [q.get(k) for q in reqs]
        if not all(v == vals[0] for v in vals):
            differences.append(
                {
                    "condition": k,
                    "values": vals,
                    "kind": "treatment",
                    "note": f"defined treatment: {label}",
                }
            )
    kinds = [r.result.plan_kind.value for r in runs]
    if len(set(kinds)) > 1:
        differences.append(
            {
                "condition": "plan_kind",
                "values": kinds,
                "kind": "treatment",
                "note": "baseline ladder step",
            }
        )
    compatible = not any(d["kind"] == "non_causal" for d in differences)
    return {
        "compatible": compatible,
        "compatibility_key": content_hash({k: conds[0].get(k) for k in CAUSAL_KEYS})
        if compatible
        else None,
        "shared": shared,
        "differences": differences,
        "label": "matched comparison"
        if compatible
        else "non-matched comparison: differences are not causal",
    }


def deltas(base: LoadedRun, other: LoadedRun, *, label_non_causal: bool) -> list[dict[str, Any]]:
    a, b = _mindex(base), _mindex(other)
    out = []
    for key in sorted(set(a) & set(b), key=lambda k: (k[0], k[1] or "")):
        ma, mb = a[key], b[key]
        ok = ma.status is MetricStatus.available and mb.status is MetricStatus.available
        out.append(
            {
                "metric_id": key[0],
                "definition_id": ma.definition_id,
                "field_id": key[1],
                "unit": ma.unit,
                "a": ma.value,
                "b": mb.value,
                "delta": (mb.value - ma.value) if ok else None,
                "status": "available" if ok else "not_comparable",
                "a_run_id": base.run_id,
                "b_run_id": other.run_id,
                "causal": not label_non_causal,
            }
        )
    return out


def compare(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, Any]:
    if len(run_ids) < 2 or len(set(run_ids)) != len(run_ids):
        raise invalid(
            "a comparison needs at least two distinct run IDs", {"run_ids": "need >= 2 distinct"}
        )
    runs = [load_run(conn, r) for r in run_ids]
    cert = certificate(runs)
    base = runs[0]
    rows = []
    plans = []
    for r in runs:
        res = r.result
        plans.append(
            {
                "run_id": r.run_id,
                "plan_kind": res.plan_kind.value,
                "outcome": res.outcome,
                "solver_status": res.solver_status.value,
            }
        )
    for r in runs[1:]:
        if base.result.outcome != "plan" or r.result.outcome != "plan":
            continue
        rows.extend(deltas(base, r, label_non_causal=not cert["compatible"]))
    incremental = []
    for x, y in itertools.pairwise(runs):
        if x.result.outcome == "plan" and y.result.outcome == "plan":
            ax, ay = _mindex(x), _mindex(y)
            step = {
                "from_run_id": x.run_id,
                "to_run_id": y.run_id,
                "step": f"{x.result.plan_kind.value}->{y.result.plan_kind.value}",
            }
            for mid in (
                "production_kg",
                "operating_cost_pkr",
                "capital_commitment_pkr",
                "groundwater_m3",
                "canal_source_withdrawal_m3",
                "min_service_ratio",
            ):
                ma, mb = ax.get((mid, None)), ay.get((mid, None))
                if ma and mb and ma.value is not None and mb.value is not None:
                    step[mid] = mb.value - ma.value
            if step.get("production_kg", 0) > 0 and (
                step.get("groundwater_m3", 0) > 0 or step.get("operating_cost_pkr", 0) > 0
            ):
                step["note"] = "greater output also uses more pumping or operating expenditure"
            incremental.append(step)
    worse = []
    if len(runs) == 2 and rows:
        for d in rows:
            if (
                d["metric_id"] == "field_production_kg"
                and d["delta"] is not None
                and d["delta"] < -QUANTUM_KG
            ):
                worse.append(d["field_id"])
    return {
        "run_ids": run_ids,
        "certificate": cert,
        "compatible": cert["compatible"],
        "compatibility_key": cert["compatibility_key"],
        "labels": {"comparison": cert["label"]},
        "plans": plans,
        "deltas": rows,
        "incremental": incremental,
        "fields_worse_off": sorted(worse),
        "metrics_version": METRICS_VERSION,
    }


def store_comparison(conn: sqlite3.Connection, result: dict[str, Any]) -> str:
    cid = new_id("cmp")
    with tx(conn):
        conn.execute(
            "INSERT INTO comparisons (comparison_id, run_ids, result, created_at) VALUES (?,?,?,?)",
            (cid, dumps(result["run_ids"]), dumps(result), utcnow()),
        )
    return cid


def get_comparison(conn: sqlite3.Connection, cid: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT result FROM comparisons WHERE comparison_id = ?", (cid,)).fetchone()
    return loads(row["result"]) if row else None


# ------------------------------------------------------------------- water accounting


def accounting(run: LoadedRun) -> dict[str, Any]:
    """Boundary-specific ledger totals and a reconciling flow list for a Sankey (PRD §8.4)."""
    if run.result.outcome != "plan":
        return {
            "run_id": run.run_id,
            "available": False,
            "reason": f"run outcome {run.result.outcome}: no plan ledger",
        }
    led = run.ledger()
    typ = run.meta["typical_state"]
    led = led[led["state_id"] == typ]
    tot = led.groupby("kind")["volume_m3"].sum().to_dict()
    g = lambda k: float(tot.get(k, 0.0))
    src, loss, receipt = g("source_release"), g("edge_loss"), g("outlet_receipt")
    fill, release, appl = g("pond_fill"), g("pond_release"), g("field_application")
    pump, rain = g("pump_abstraction"), g("pond_rain")
    evap, seep, spill = g("pond_evaporation"), g("pond_seepage"), g("pond_spill")
    direct = max(0.0, receipt - fill)
    flows = [
        {"from": "canal_source", "to": "conveyance_loss", "m3": loss},
        {"from": "canal_source", "to": "outlet_receipt", "m3": src - loss},
        {"from": "outlet_receipt", "to": "pond_storage", "m3": fill},
        {"from": "outlet_receipt", "to": "direct_field_application", "m3": direct},
        {"from": "pond_rain", "to": "pond_storage", "m3": rain},
        {"from": "pond_storage", "to": "field_application_from_pond", "m3": release},
        {"from": "pond_storage", "to": "pond_losses", "m3": evap + seep},
        {"from": "pond_storage", "to": "pond_spill", "m3": spill},
        {"from": "groundwater", "to": "field_application_from_pump", "m3": pump},
    ]
    per_field = defaultdict(lambda: defaultdict(float))
    for row in led.itertuples():
        if isinstance(row.field_id, str) and row.field_id:
            per_field[row.field_id][row.kind] += float(row.volume_m3)
    pond_balance = rain + fill - release - evap - seep - spill
    sel = run.json("selection.json") or {}
    terminal = sum(
        (f.get("outcomes", {}).get(typ, {}) or {}).get("terminal_pond_m3", 0.0)
        for f in sel.get("fields", {}).values()
    )
    return {
        "run_id": run.run_id,
        "state_id": typ,
        "available": True,
        "boundaries": {
            "canal_source_withdrawal_m3": src,
            "conveyance_loss_m3": loss,
            "outlet_receipt_m3": receipt,
            "pond_fill_m3": fill,
            "pond_release_m3": release,
            "pond_rain_m3": rain,
            "pond_evaporation_m3": evap,
            "pond_seepage_m3": seep,
            "pond_spill_m3": spill,
            "pond_net_storage_change_m3": pond_balance,
            "terminal_pond_inventory_m3": terminal,
            "groundwater_abstraction_m3": pump,
            "gross_field_application_m3": appl,
        },
        "flows": [f for f in flows if f["m3"] > 0],
        "reconciliation": {
            "source_minus_loss_minus_receipt_m3": src - loss - receipt,
            "note": "source withdrawal = conveyance loss + outlet receipt (within float tolerance); soil-water and "
            "network/pond accounting are separate; ET components are not summed as losses",
        },
        "per_field": {f: dict(v) for f, v in sorted(per_field.items())},
        "basin_savings": {
            "status": "not_estimated",
            "reason": "return flows and a basin boundary are not modeled",
        },
    }


# ---------------------------------------------------------------------------- equity


def equity(
    conn: sqlite3.Connection, run: LoadedRun, baseline: LoadedRun | None, pilots: PilotRepository
) -> dict:
    if run.result.outcome != "plan":
        return {
            "run_id": run.run_id,
            "available": False,
            "reason": f"run outcome {run.result.outcome}",
        }
    m = _mindex(run)
    meta = run.meta
    pkg = pilots.package(meta["pilot_id"], meta["pilot_version"])
    rows = []
    for fid, rec in sorted(pkg.fields.items()):
        sr = m.get(("field_service_ratio", fid))
        prod = m.get(("field_production_kg", fid))
        gw = m.get(("field_groundwater_m3", fid))
        row = {
            "field_id": fid,
            "group": rec.group,
            "owner_ref": rec.owner_ref,
            "service_ratio": sr.value if sr else None,
            "service_status": sr.status.value if sr else "not_estimated",
            "production_kg": prod.value if prod else None,
            "groundwater_m3": gw.value if gw else None,
            "production_delta_kg": None,
        }
        rows.append(row)
    cert = None
    worse: list[str] = []
    if baseline is not None:
        cert = certificate([baseline, run])
        if baseline.result.outcome == "plan":
            bm = _mindex(baseline)
            for row in rows:
                a = bm.get(("field_production_kg", row["field_id"]))
                if a and a.value is not None and row["production_kg"] is not None:
                    row["production_delta_kg"] = row["production_kg"] - a.value
                    if row["production_delta_kg"] < -QUANTUM_KG:
                        worse.append(row["field_id"])
    groups = {}
    for g in ("head", "middle", "tail"):
        vals = [
            r["service_ratio"] for r in rows if r["group"] == g and r["service_ratio"] is not None
        ]
        groups[g] = {
            "fields": sum(1 for r in rows if r["group"] == g),
            "eligible": len(vals),
            "mean_service_ratio": sum(vals) / len(vals) if vals else None,
            "min_service_ratio": min(vals) if vals else None,
        }
    zero_ref = [r["field_id"] for r in rows if r["service_status"] == "not_applicable"]
    gw_total = sum(r["groundwater_m3"] or 0 for r in rows)
    burden = (
        {r["field_id"]: (r["groundwater_m3"] or 0) / gw_total for r in rows} if gw_total > 0 else {}
    )
    owners = defaultdict(list)
    for r in rows:
        if r["owner_ref"]:
            owners[r["owner_ref"]].append(r["field_id"])
    return {
        "run_id": run.run_id,
        "baseline_run_id": baseline.run_id if baseline else None,
        "available": True,
        "measure_label": "receipt / reference allowance",
        "aggregation": "field-weighted",
        "fields": rows,
        "groups": groups,
        "min_service_ratio": (
            m.get(("min_service_ratio", None)).value if m.get(("min_service_ratio", None)) else None
        ),
        "zero_reference_fields": zero_ref,
        "fields_worse_off": worse,
        "fields_worse_off_count": len(worse) if baseline is not None else None,
        "pumping_burden_share": burden,
        "owner_aggregation": {o: fs for o, fs in owners.items()} if owners else None,
        "owner_note": None
        if owners
        else "no ownership mapping supplied; results are per field, not per household",
        "comparison": cert,
    }


# ------------------------------------------------------------------- economics & plan


def economics(run: LoadedRun, pilots: PilotRepository) -> dict[str, Any]:
    if run.result.outcome != "plan":
        return {
            "run_id": run.run_id,
            "available": False,
            "reason": f"run outcome {run.result.outcome}",
        }
    m = _mindex(run)
    meta = run.meta
    pkg = pilots.package(meta["pilot_id"], meta["pilot_version"])
    sel = run.json("selection.json")
    scen = run.json("scenario.json")["request"]
    inst_ids = list(run.result.selected_intervention_instance_ids)
    items = []
    for j in inst_ids:
        inst = pkg.instances.get(j)
        if inst is None:
            continue
        items.append(
            {
                "instance_id": j,
                "category": inst.category.value,
                "capex_pkr": inst.capex_pkr,
                "seasonal_opex_pkr": inst.seasonal_opex_pkr,
                "shared": inst.shared,
                "charged": "once (shared configuration)"
                if inst.category.value == "shared_repair"
                else "once",
                "evidence_ids": inst.evidence_ids,
            }
        )
    pumping = [
        {
            "field_id": f,
            "seasonal_opex_pkr": v["seasonal_opex_pkr"],
            "pump_volume_m3": v["pump_volume_m3"],
        }
        for f, v in sel["fields"].items()
        if v["seasonal_opex_pkr"] or v["pump_volume_m3"]
    ]
    gross = m[("capital_commitment_pkr", None)].value
    opex = m[("operating_cost_pkr", None)].value
    crop_value = m.get(("crop_value_pkr", None))
    contrib = m.get(("irrigation_contribution_pkr", None))
    sens = []
    for label, factor in (("capital cost -20%", 0.8), ("capital cost +20%", 1.2)):
        sens.append(
            {
                "case": label,
                "gross_capital_pkr": gross * factor,
                "within_budget": gross * factor <= scen["capital_budget_pkr"],
            }
        )
    for label, factor in (("operating cost -20%", 0.8), ("operating cost +20%", 1.2)):
        sens.append(
            {
                "case": label,
                "operating_pkr": opex * factor,
                "within_budget": opex * factor <= scen["operating_budget_pkr"],
            }
        )
    return {
        "run_id": run.run_id,
        "available": True,
        "gross_project_cost_pkr": gross,
        "capital_budget_pkr": scen["capital_budget_pkr"],
        "public_grant_pkr": {
            "status": "not_applicable",
            "reason": "no verified program/site/applicant grant record",
        },
        "participant_cash_pkr": gross,
        "seasonal_operating_pkr": opex,
        "operating_budget_pkr": scen["operating_budget_pkr"],
        "pumping": pumping,
        "instances": items,
        "crop_value": crop_value.model_dump(mode="json") if crop_value else None,
        "irrigation_contribution": contrib.model_dump(mode="json") if contrib else None,
        "sensitivity": sens,
        "sensitivity_note": "budget-feasibility under uncertain costs; a changed cost requires a new solve to know "
        "whether the selection changes",
        "cashflow": {
            "status": "not_estimated",
            "reason": "multi-year projection needs a documented asset life, crop price and discount rate",
        },
    }


ROLE_BY_CATEGORY = {
    "pond": ("Field owner with WUA coordinator", "WUA committee approval; site/land check"),
    "leveling": ("Field owner with leveling service provider", "Field owner consent"),
    "shared_repair": (
        "WUA coordinator with irrigation department",
        "Irrigation department / WUA committee",
    ),
    "pump_supplement": ("Pump operator", "Pump owner/shared-use agreement"),
    "timing": ("Field owner during permitted turns", "None beyond the existing roster"),
}


def action_plan(run: LoadedRun, pilots: PilotRepository) -> dict[str, Any]:
    if run.result.outcome != "plan":
        return {
            "run_id": run.run_id,
            "available": False,
            "reason": f"run outcome {run.result.outcome}: no plan",
        }
    meta = run.meta
    pkg = pilots.package(meta["pilot_id"], meta["pilot_version"])
    scen = run.json("scenario.json")["request"]
    sel = run.json("selection.json")
    m = _mindex(run)
    decision = local_crop_date(datetime.fromisoformat(scen["decision_at"]))
    actions = []
    for j in run.result.selected_intervention_instance_ids:
        inst = pkg.instances.get(j)
        if inst is None:
            continue
        start = decision + timedelta(days=inst.procurement_delay_days)
        comm = start + timedelta(days=inst.lead_time_days)
        affected = [f for f, v in sel["fields"].items() if j in v["required_instance_ids"]]
        if inst.category.value == "shared_repair":
            affected = sorted(sel["fields"])
        role, approval = ROLE_BY_CATEGORY[inst.category.value]
        actions.append(
            {
                "action_id": j,
                "category": inst.category.value,
                "target_ids": inst.target_ids,
                "description": f"{inst.category.value.replace('_', ' ')} {j}",
                "crop_season": meta["season_id"],
                "decision_date": decision.isoformat(),
                "start_date": start.isoformat(),
                "commissioning_date": comm.isoformat(),
                "quantity": inst.parameters,
                "capex_pkr": inst.capex_pkr,
                "seasonal_opex_pkr": inst.seasonal_opex_pkr,
                "payer": "assumed: participants (no verified grant)",
                "responsible_role": role,
                "required_approval": approval,
                "prerequisites": inst.prerequisites,
                "affected_fields": affected,
                "modeled_change": {
                    f: m.get(("field_production_kg", f)).value
                    if m.get(("field_production_kg", f))
                    else None
                    for f in affected
                },
                "uncertainty": "model output; costs and effects are configured assumptions unless evidence says otherwise",
                "source_refs": inst.evidence_ids,
                "run_id": run.run_id,
                "status": "proposed",
            }
        )
    schedules = []
    for f, v in sorted(sel["fields"].items()):
        for e in v["application_schedule"]:
            schedules.append(
                {
                    "field_id": f,
                    "date": e["date"],
                    "gross_depth_mm": e["gross_depth_mm"],
                    "policy_family": v["family"],
                }
            )
        if v["family"] not in ("baseline_B0",) and not v["required_instance_ids"]:
            actions.append(
                {
                    "action_id": f"{f}:operations",
                    "category": "timing",
                    "target_ids": [f],
                    "description": f"operate {f} with policy family {v['family']}",
                    "crop_season": meta["season_id"],
                    "decision_date": decision.isoformat(),
                    "start_date": None,
                    "commissioning_date": None,
                    "quantity": {"gross_application_mm": v["gross_application_mm"]},
                    "capex_pkr": 0,
                    "seasonal_opex_pkr": v["seasonal_opex_pkr"],
                    "payer": "field operator",
                    "responsible_role": ROLE_BY_CATEGORY["timing"][0],
                    "required_approval": ROLE_BY_CATEGORY["timing"][1],
                    "prerequisites": v["uses_asset_ids"],
                    "affected_fields": [f],
                    "modeled_change": {
                        f: m.get(("field_production_kg", f)).value
                        if m.get(("field_production_kg", f))
                        else None
                    },
                    "uncertainty": "model output",
                    "source_refs": [],
                    "run_id": run.run_id,
                    "status": "proposed",
                }
            )
    return {
        "run_id": run.run_id,
        "available": True,
        "plan_kind": run.result.plan_kind.value,
        "actions": actions,
        "schedules": schedules,
        "status_note": "'accepted' records the local user's decision only; it is not an authorization or work order",
    }


# --------------------------------------------------------------------------- impact


SDG_CARDS = [
    {
        "card": "SDG 2.4",
        "metrics": [
            "sdg_2_4_production_retained_fraction",
            "production_kg",
            "worst_tested_production_kg",
        ],
        "interpretation": "Model-based planning resilience, not measured food security",
        "target_url": "https://sdgs.un.org/goals/goal2",
    },
    {
        "card": "SDG 6.4/6.5",
        "metrics": [
            "sdg_6_4_water_productivity_kg_m3",
            "groundwater_m3",
            "sdg_6_5_min_entitlement_fulfillment",
        ],
        "interpretation": "Water productivity, accounting and participation proxies, not official UN indicator scores",
        "target_url": "https://sdgs.un.org/goals/goal6",
    },
    {
        "card": "SDG 13.1",
        "metrics": ["sdg_13_1_worst_tested_production_kg"],
        "interpretation": "Scenario robustness within tested states, not quantified disaster-risk reduction",
        "target_url": "https://sdgs.un.org/goals/goal13",
    },
]


def impact(run: LoadedRun, baseline: LoadedRun | None, stress: dict | None) -> dict[str, Any]:
    if run.result.outcome != "plan":
        return {
            "run_id": run.run_id,
            "available": False,
            "reason": f"run outcome {run.result.outcome}",
        }
    m = _mindex(run)
    extra: list[MetricValue] = []
    if baseline is not None and baseline.result.outcome == "plan":
        cert = certificate([baseline, run])
        bm = _mindex(baseline)
        a, b = bm.get(("groundwater_m3", None)), m.get(("groundwater_m3", None))
        if cert["compatible"] and a and b and a.value is not None and b.value is not None:
            extra.append(mv("sdg_6_4_groundwater_change_m3", run.run_id, b.value - a.value))
        else:
            extra.append(
                mv(
                    "sdg_6_4_groundwater_change_m3",
                    run.run_id,
                    None,
                    status=MetricStatus.not_applicable,
                    reason="baseline is not a compatible comparison",
                )
            )
    if stress is not None:
        for k in (
            "worst_tested_production_kg",
            "sdg_13_1_worst_tested_production_kg",
            "sdg_2_4_production_retained_fraction",
        ):
            if k in stress:
                extra.append(MetricValue.model_validate(stress[k]))
    by = dict(m)
    for e in extra:
        by[(e.metric_id, e.field_id)] = e
    cards = []
    for c in SDG_CARDS:
        mids = list(c["metrics"]) + (
            ["sdg_6_4_groundwater_change_m3"] if c["card"] == "SDG 6.4/6.5" else []
        )
        vals = [by[(k, None)].model_dump(mode="json") for k in mids if (k, None) in by]
        cards.append(
            {
                **c,
                "official_indicator": False,
                "values": vals,
                "formulas": {k: REGISTRY[k].formula for k in mids if k in REGISTRY},
                "run_ids": [run.run_id] + ([baseline.run_id] if baseline else []),
                "limitations": [
                    "project proxy computed from model output",
                    "no 0-100 score",
                    "no CO2 estimate without cited energy and emission factors",
                ],
            }
        )
    dist = [
        {"field_id": k[1], "production_kg": v.value}
        for k, v in m.items()
        if k[0] == "field_production_kg"
    ]
    return {
        "run_id": run.run_id,
        "available": True,
        "cards": cards,
        "distribution": dist,
        "co2": {
            "status": "not_estimated",
            "reason": "no energy, fuel/grid factor and system boundary supplied",
        },
    }
