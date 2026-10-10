"""Server metric registry (T7.5): one set of definitions for UI, reports and chat.

Every displayed KPI is a ``MetricValue`` computed here from exact stored crop
outcomes and the reconstructed original-precision ledger. Nothing downstream
recomputes yields, money or service with different formulas.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from aabflow.domain.schemas import LedgerEvent, MetricStatus, MetricValue

METRICS_VERSION = "metrics-1.0.0"


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    label: str
    unit: str
    formula: str
    boundary: str
    aggregation: str
    missing: str
    scope: str = "run"  # run | field | analysis
    higher_is: str = "neutral"  # better | worse | neutral (for display palettes only)
    official_indicator: bool = False
    sdg_alignment: str | None = None
    evidence_dependencies: tuple[str, ...] = ()

    @property
    def definition_id(self) -> str:
        return f"{self.metric_id}@{METRICS_VERSION}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "definition_id": self.definition_id,
            "label": self.label,
            "unit": self.unit,
            "formula": self.formula,
            "boundary": self.boundary,
            "aggregation": self.aggregation,
            "missing": self.missing,
            "scope": self.scope,
            "higher_is": self.higher_is,
            "official_indicator": self.official_indicator,
            "sdg_alignment": self.sdg_alignment,
            "evidence_dependencies": list(self.evidence_dependencies),
        }


_DEFS = [
    MetricDefinition("production_kg", "Modeled crop production", "kg",
                     "sum over fields of cropped_area_ha x exact_yield_kg_ha", "harvested crop, selected crop only",
                     "sum over fields", "null when any selected field lacks an exact crop outcome", "run", "better"),
    MetricDefinition("field_production_kg", "Field modeled production", "kg", "cropped_area_ha x exact_yield_kg_ha",
                     "field", "per field", "null without an exact outcome", "field", "better"),
    MetricDefinition("field_yield_kg_ha", "Field modeled yield", "kg/ha", "exact AquaCrop yield in the crop's yield basis",
                     "field", "per field", "null without an exact outcome", "field", "better"),
    MetricDefinition("field_cropped_area_ha", "Field cropped area", "ha",
                     "gross_area_ha minus new pond footprint (subtracted once)", "field", "per field", "never missing",
                     "field"),
    MetricDefinition("cropped_area_ha", "Total cropped area", "ha", "sum of field cropped area", "pilot", "sum",
                     "never missing"),
    MetricDefinition("capital_commitment_pkr", "Gross capital commitment", "PKR",
                     "shared configuration capex (charged once) + sum of selected field-level instance capex",
                     "gross project commitment; grants are not netted", "sum", "never missing", "run", "worse"),
    MetricDefinition("operating_cost_pkr", "Seasonal operating cost", "PKR",
                     "sum of selected policy variable costs (pumping) + selected instance seasonal opex + shared opex",
                     "season", "sum", "never missing", "run", "worse"),
    MetricDefinition("pumping_cost_pkr", "Seasonal pumping cost", "PKR", "sum of selected policies' pumping cost",
                     "season", "sum", "never missing", "run", "worse"),
    MetricDefinition("canal_source_withdrawal_m3", "Canal source withdrawal", "m3",
                     "sum of source_release ledger events", "declared source node", "sum", "null without a ledger",
                     "run", "neutral"),
    MetricDefinition("conveyance_loss_m3", "Conveyance loss", "m3", "sum of edge_loss ledger events",
                     "modeled reaches", "sum", "null without a ledger", "run", "worse"),
    MetricDefinition("outlet_receipt_m3", "Canal water received at fields", "m3",
                     "sum of outlet_receipt ledger events", "field accounting boundary", "sum",
                     "null without a ledger"),
    MetricDefinition("field_application_m3", "Gross field application", "m3",
                     "sum of field_application ledger events", "field", "sum", "null without a ledger"),
    MetricDefinition("groundwater_m3", "Groundwater abstraction", "m3", "sum of pump_abstraction ledger events",
                     "pump injection points", "sum", "null without a ledger", "run", "worse"),
    MetricDefinition("pond_losses_m3", "Pond evaporation and seepage", "m3",
                     "sum of pond_evaporation + pond_seepage ledger events", "ponds", "sum", "null without a ledger",
                     "run", "worse"),
    MetricDefinition("pond_spill_m3", "Pond spill", "m3", "sum of pond_spill ledger events", "ponds", "sum",
                     "null without a ledger", "run", "worse"),
    MetricDefinition("pond_rain_m3", "Pond rainfall capture", "m3", "sum of pond_rain ledger events", "ponds", "sum",
                     "null without a ledger"),
    MetricDefinition("terminal_pond_m3", "Pond inventory at season end", "m3",
                     "sum over selected policies of terminal pond inventory; no salvage value", "ponds", "sum",
                     "never missing"),
    MetricDefinition("withdrawal_productivity_kg_m3", "Withdrawal productivity", "kg/m3",
                     "production_kg / (canal_source_withdrawal_m3 + groundwater_m3)",
                     "canal source + groundwater withdrawals", "ratio of sums",
                     "not_applicable when withdrawal is zero", "run", "better", False, "SDG 6.4 proxy"),
    MetricDefinition("field_service_ratio", "Receipt / reference allowance", "ratio",
                     "credited canal receipt at the field / fixed reference allowance",
                     "field accounting boundary", "per field",
                     "not_applicable for zero-reference fields; values above one are not clamped", "field", "better"),
    MetricDefinition("min_service_ratio", "Minimum field service", "ratio", "min field_service_ratio over eligible fields",
                     "field", "minimum, field-weighted", "excludes zero-reference fields", "run", "better", False,
                     "SDG 6.5 proxy"),
    MetricDefinition("head_mean_service_ratio", "Head fields mean service", "ratio",
                     "mean field_service_ratio over head fields", "field", "field-weighted mean",
                     "excludes zero-reference fields", "run", "better"),
    MetricDefinition("middle_mean_service_ratio", "Middle fields mean service", "ratio",
                     "mean field_service_ratio over middle fields", "field", "field-weighted mean",
                     "excludes zero-reference fields", "run", "better"),
    MetricDefinition("tail_mean_service_ratio", "Tail fields mean service", "ratio",
                     "mean field_service_ratio over tail fields", "field", "field-weighted mean",
                     "excludes zero-reference fields", "run", "better"),
    MetricDefinition("tail_min_service_ratio", "Tail minimum service", "ratio",
                     "min field_service_ratio over tail fields", "field", "minimum", "excludes zero-reference fields",
                     "run", "better"),
    MetricDefinition("field_groundwater_m3", "Field groundwater use", "m3", "selected policy pumped volume",
                     "field", "per field", "never missing", "field", "worse"),
    MetricDefinition("field_canal_receipt_m3", "Field canal receipt", "m3", "selected policy canal receipt at field",
                     "field", "per field", "never missing", "field"),
    MetricDefinition("new_instances_count", "New intervention instances", "count",
                     "number of selected new intervention instances (incl. shared repairs)", "pilot", "count",
                     "never missing"),
    MetricDefinition("crop_value_pkr", "Modeled crop value", "PKR", "production_kg x dated crop price (PKR/kg)",
                     "farmgate/wholesale basis of the price record", "sum",
                     "not_estimated without a dated price record", "run", "better"),
    MetricDefinition("irrigation_contribution_pkr", "Irrigation contribution", "PKR",
                     "crop_value_pkr - decision-dependent seasonal irrigation costs (not farm profit, not NPV)",
                     "season", "sum", "not_estimated without price and complete variable costs", "run", "better"),
    MetricDefinition("worst_tested_production_kg", "Worst tested production", "kg",
                     "min production over the run's evaluated states (robust plans: every state deliverable)",
                     "tested states only", "minimum", "blocked when any tested state is undeliverable", "run",
                     "better", False, "SDG 13.1 proxy"),
    MetricDefinition("typical_production_kg", "Production in the typical state", "kg",
                     "production_kg in the designated typical state", "typical state", "sum",
                     "null without an exact outcome", "run", "better"),
    MetricDefinition("objective_quantization_bound_kg", "Objective quantization bound", "kg",
                     "fields x production quantum (floor rounding of objective coefficients)", "solver", "bound",
                     "never missing"),
    # SDG project proxies (official_indicator=false)
    MetricDefinition("sdg_2_4_production_retained_fraction", "Production retained across tested scenarios", "ratio",
                     "worst_tested_production_kg / typical_production_kg", "tested states", "ratio",
                     "blocked if any tested state undeliverable; not_applicable without a multi-state evaluation",
                     "analysis", "better", False, "SDG 2.4 (sustainable food production) project proxy"),
    MetricDefinition("sdg_6_4_water_productivity_kg_m3", "Crop per drop (withdrawal productivity)", "kg/m3",
                     "production_kg / (canal_source_withdrawal_m3 + groundwater_m3)", "defined withdrawals", "ratio",
                     "not_applicable when withdrawal is zero", "run", "better", False,
                     "SDG 6.4 (water-use efficiency) project proxy"),
    MetricDefinition("sdg_6_4_groundwater_change_m3", "Groundwater change vs baseline", "m3",
                     "groundwater_m3(run) - groundwater_m3(baseline)", "pumps", "difference",
                     "not_applicable without a compatible baseline", "analysis", "worse", False,
                     "SDG 6.4 project proxy"),
    MetricDefinition("sdg_6_5_min_entitlement_fulfillment", "Minimum entitlement fulfillment", "ratio",
                     "min field_service_ratio (receipt / reference allowance)", "field", "minimum",
                     "excludes zero-reference fields", "run", "better", False,
                     "SDG 6.5 (integrated water management/participation) project proxy"),
    MetricDefinition("sdg_13_1_worst_tested_production_kg", "Worst tested scenario outcome", "kg",
                     "min production over tested states; difference from typical-case plan shown alongside",
                     "tested states", "minimum", "blocked if any tested state undeliverable", "analysis", "better",
                     False, "SDG 13.1 (resilience) project proxy"),
    # Comparison / equity
    MetricDefinition("field_production_delta_kg", "Field production change", "kg",
                     "field_production_kg(run) - field_production_kg(baseline)", "field", "per field",
                     "null when either side lacks an exact outcome", "field", "better"),
    MetricDefinition("fields_worse_off_count", "Fields worse off", "count",
                     "number of fields with field_production_delta_kg < -quantum", "field", "count",
                     "requires a compatible baseline", "analysis", "worse"),
]

REGISTRY: dict[str, MetricDefinition] = {d.metric_id: d for d in _DEFS}


def definition(metric_id: str) -> MetricDefinition:
    return REGISTRY[metric_id]


def mv(
    metric_id: str,
    run_id: str,
    value: float | None,
    *,
    status: MetricStatus | None = None,
    reason: str | None = None,
    field_id: str | None = None,
    crop: str | None = None,
    evidence_ids: Iterable[str] = (),
) -> MetricValue:
    d = REGISTRY[metric_id]
    if status is None:
        status = MetricStatus.available if value is not None else MetricStatus.not_estimated
    if status is not MetricStatus.available:
        value = None
    return MetricValue(
        metric_id=metric_id,
        definition_id=d.definition_id,
        run_id=run_id,
        value=None if value is None else float(value),
        unit=d.unit,
        status=status,
        reason=reason,
        evidence_ids=sorted(set(evidence_ids)),
        crop=crop,
        field_id=field_id,
    )


# ---------------------------------------------------------------------------- inputs


@dataclass
class FieldFacts:
    field_id: str
    group: str
    policy_id: str
    family: str
    cropped_area_ha: float
    yield_kg_ha: float | None
    production_kg: float | None
    canal_receipt_m3: float
    service_credit_m3: float
    reference_m3: float | None
    groundwater_m3: float
    pumping_cost_pkr: int
    terminal_pond_m3: float = 0.0
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class PlanFacts:
    run_id: str
    crop: str
    state_id: str
    fields: list[FieldFacts]
    ledger: list[LedgerEvent] | None
    capital_pkr: int
    operating_pkr: int
    pumping_pkr: int
    new_instance_ids: list[str]
    price_pkr_per_kg: str | None = None
    price_evidence_id: str | None = None
    per_state_production: dict[str, float | None] = field(default_factory=dict)
    typical_state_id: str | None = None
    production_quantum_kg: float = 0.1
    evidence_ids: list[str] = field(default_factory=list)


def ledger_totals(events: Iterable[LedgerEvent]) -> dict[str, float]:
    tot: dict[str, float] = {}
    for e in events:
        tot[e.kind.value] = tot.get(e.kind.value, 0.0) + e.volume_m3
    return tot


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute_plan_metrics(f: PlanFacts) -> list[MetricValue]:
    rid, crop = f.run_id, f.crop
    out: list[MetricValue] = []
    ev = f.evidence_ids
    prods = [x.production_kg for x in f.fields]
    total_prod = None if any(p is None for p in prods) else float(sum(prods))
    reason = None if total_prod is not None else "a selected field lacks an exact crop outcome"
    out.append(mv("production_kg", rid, total_prod, crop=crop, reason=reason, evidence_ids=ev))
    out.append(mv("cropped_area_ha", rid, sum(x.cropped_area_ha for x in f.fields)))
    out.append(mv("capital_commitment_pkr", rid, f.capital_pkr))
    out.append(mv("operating_cost_pkr", rid, f.operating_pkr))
    out.append(mv("pumping_cost_pkr", rid, f.pumping_pkr))
    out.append(mv("new_instances_count", rid, len(f.new_instance_ids)))
    out.append(mv("terminal_pond_m3", rid, sum(x.terminal_pond_m3 for x in f.fields)))
    n = len(f.fields)
    out.append(mv("objective_quantization_bound_kg", rid, n * f.production_quantum_kg))

    if f.ledger is not None:
        t = ledger_totals(f.ledger)
        src = t.get("source_release", 0.0)
        gw = t.get("pump_abstraction", 0.0)
        out.append(mv("canal_source_withdrawal_m3", rid, src))
        out.append(mv("conveyance_loss_m3", rid, t.get("edge_loss", 0.0)))
        out.append(mv("outlet_receipt_m3", rid, t.get("outlet_receipt", 0.0)))
        out.append(mv("field_application_m3", rid, t.get("field_application", 0.0)))
        out.append(mv("groundwater_m3", rid, gw))
        out.append(mv("pond_losses_m3", rid, t.get("pond_evaporation", 0.0) + t.get("pond_seepage", 0.0)))
        out.append(mv("pond_spill_m3", rid, t.get("pond_spill", 0.0)))
        out.append(mv("pond_rain_m3", rid, t.get("pond_rain", 0.0)))
        wd = src + gw
        for mid in ("withdrawal_productivity_kg_m3", "sdg_6_4_water_productivity_kg_m3"):
            if wd <= 0:
                out.append(mv(mid, rid, None, status=MetricStatus.not_applicable, reason="zero withdrawal", crop=crop))
            elif total_prod is None:
                out.append(mv(mid, rid, None, status=MetricStatus.not_estimated, reason=reason, crop=crop))
            else:
                out.append(mv(mid, rid, total_prod / wd, crop=crop))
    else:
        for mid in ("canal_source_withdrawal_m3", "conveyance_loss_m3", "outlet_receipt_m3", "field_application_m3",
                    "groundwater_m3", "pond_losses_m3", "pond_spill_m3", "pond_rain_m3",
                    "withdrawal_productivity_kg_m3", "sdg_6_4_water_productivity_kg_m3"):
            out.append(mv(mid, rid, None, status=MetricStatus.blocked, reason="no reconstructed ledger"))

    # per field
    ratios: dict[str, list[float]] = {"head": [], "middle": [], "tail": []}
    all_ratios: list[float] = []
    for x in f.fields:
        fid = x.field_id
        out.append(mv("field_cropped_area_ha", rid, x.cropped_area_ha, field_id=fid))
        out.append(mv("field_yield_kg_ha", rid, x.yield_kg_ha, field_id=fid, crop=crop, evidence_ids=x.evidence_ids))
        out.append(mv("field_production_kg", rid, x.production_kg, field_id=fid, crop=crop, evidence_ids=x.evidence_ids))
        out.append(mv("field_groundwater_m3", rid, x.groundwater_m3, field_id=fid))
        out.append(mv("field_canal_receipt_m3", rid, x.canal_receipt_m3, field_id=fid))
        if not x.reference_m3:
            out.append(mv("field_service_ratio", rid, None, status=MetricStatus.not_applicable,
                          reason="zero or missing reference allowance", field_id=fid))
        else:
            r = x.service_credit_m3 / x.reference_m3
            all_ratios.append(r)
            ratios.setdefault(x.group, []).append(r)
            out.append(mv("field_service_ratio", rid, r, field_id=fid))

    def _agg(mid: str, vals: list[float], fn) -> None:
        if not vals:
            out.append(mv(mid, rid, None, status=MetricStatus.not_applicable, reason="no eligible fields"))
        else:
            out.append(mv(mid, rid, fn(vals)))

    _agg("min_service_ratio", all_ratios, min)
    _agg("sdg_6_5_min_entitlement_fulfillment", all_ratios, min)
    for g in ("head", "middle", "tail"):
        _agg(f"{g}_mean_service_ratio", ratios.get(g, []), lambda v: sum(v) / len(v))
    _agg("tail_min_service_ratio", ratios.get("tail", []), min)

    # money
    if f.price_pkr_per_kg is None:
        for mid in ("crop_value_pkr", "irrigation_contribution_pkr"):
            out.append(mv(mid, rid, None, status=MetricStatus.not_estimated, reason="no dated crop price record"))
    elif total_prod is None:
        for mid in ("crop_value_pkr", "irrigation_contribution_pkr"):
            out.append(mv(mid, rid, None, status=MetricStatus.not_estimated, reason=reason))
    else:
        value = Decimal(f.price_pkr_per_kg) * Decimal(repr(total_prod))
        cev = [f.price_evidence_id] if f.price_evidence_id else []
        out.append(mv("crop_value_pkr", rid, float(value), evidence_ids=cev))
        out.append(mv("irrigation_contribution_pkr", rid, float(value - f.operating_pkr), evidence_ids=cev))

    # multi-state
    typ = f.per_state_production.get(f.typical_state_id) if f.typical_state_id else None
    out.append(mv("typical_production_kg", rid, typ if f.typical_state_id in f.per_state_production else total_prod,
                  crop=crop))
    if len(f.per_state_production) > 1:
        vals = list(f.per_state_production.values())
        if any(v is None for v in vals):
            for mid in ("worst_tested_production_kg", "sdg_13_1_worst_tested_production_kg",
                        "sdg_2_4_production_retained_fraction"):
                out.append(mv(mid, rid, None, status=MetricStatus.blocked,
                              reason="at least one tested state is undeliverable for this plan"))
        else:
            worst = min(vals)
            out.append(mv("worst_tested_production_kg", rid, worst, crop=crop))
            out.append(mv("sdg_13_1_worst_tested_production_kg", rid, worst, crop=crop))
            ref = typ if typ else None
            out.append(mv("sdg_2_4_production_retained_fraction", rid, _ratio(worst, ref),
                          status=None if ref else MetricStatus.not_applicable,
                          reason=None if ref else "typical-state production is zero or missing"))
    else:
        out.append(mv("worst_tested_production_kg", rid, total_prod, crop=crop,
                      reason="single evaluated state: the minimum is that state's production"))
        for mid in ("sdg_13_1_worst_tested_production_kg", "sdg_2_4_production_retained_fraction"):
            out.append(mv(mid, rid, None, status=MetricStatus.not_applicable,
                          reason="needs a multi-state stress or robust evaluation"))
    return out


def index(metrics: Iterable[MetricValue]) -> dict[tuple[str, str | None], MetricValue]:
    return {(m.metric_id, m.field_id): m for m in metrics}
