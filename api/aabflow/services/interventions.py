"""Intervention instance eligibility: dates, costs, targets (T4.6, PRD §6.2).

Mirrors the commissioning rule used by candidate generation
(``water.context.instance_admissibility``): commissioned = local decision date +
procurement delay + lead time; ponds, leveling and repairs must be commissioned
by planting; proposed works need a cost. When a candidate library exists its
``excluded_instances`` reasons are reported as well, since the library is what the
optimizer actually sees.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from aabflow.domain.calendar import local_crop_date
from aabflow.domain.schemas import ActionCategory, AssetKind, InterventionInstance
from aabflow.services.pilots import PilotPackage

PRE_PLANT = {ActionCategory.pond, ActionCategory.leveling, ActionCategory.shared_repair}


def commissioned_on(inst: InterventionInstance, decision_at: datetime) -> date:
    return local_crop_date(decision_at) + timedelta(days=inst.procurement_delay_days + inst.lead_time_days)


def missing_cost(inst: InterventionInstance) -> str | None:
    if inst.category in PRE_PLANT and inst.capex_pkr <= 0 and not inst.parameters.get("zero_cost_reviewed"):
        return "capex missing (0 PKR without a reviewed zero-cost record); a missing cost is unavailable, not free"
    return None


def eligibility(
    pkg: PilotPackage, inst: InterventionInstance, decision_at: datetime | None, planting: date | None
) -> tuple[date | None, list[str]]:
    reasons: list[str] = []
    mc = missing_cost(inst)
    if mc:
        reasons.append(mc)
    for tid in inst.target_ids:
        if tid not in pkg.fields and tid not in pkg.edges and tid not in pkg.assets:
            reasons.append(f"target {tid} is not in pilot version {pkg.pilot_version}")
    for pre in inst.prerequisites:
        if pre not in pkg.instances and pre not in pkg.assets:
            reasons.append(f"prerequisite {pre} is not in pilot version {pkg.pilot_version}")
    if inst.category is ActionCategory.pump_supplement:
        for tid in inst.target_ids:
            a = pkg.assets.get(tid)
            if a is not None and (a.kind is not AssetKind.pump or not a.existing):
                reasons.append("pump supplementation needs an existing pump asset")
    on = commissioned_on(inst, decision_at) if decision_at else None
    if on and planting and inst.category in PRE_PLANT and on > planting:
        reasons.append(
            f"commissioned {on.isoformat()} after planting {planting.isoformat()} "
            f"(decision {local_crop_date(decision_at).isoformat()} + {inst.procurement_delay_days} procurement + "
            f"{inst.lead_time_days} lead-time days); v2 requires commissioning before planting"
        )
    return on, reasons
