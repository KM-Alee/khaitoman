"""SDG proxy cards assembled from stored MetricValues (PRD §8.5, T7.5).

Displayed proxy numbers are the stored records. A ratio is not divided again.
A blocked tested-state metric stays blocked: the worst outcome is not the
minimum over surviving cells. Field-change rows subtract stored field production
only when both sides are available and the baseline comparison is compatible.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from aabflow.domain.schemas import MetricStatus, MetricValue, StrictModel
from aabflow.services.impact.targets import (
    CO2_LIMIT,
    CO2_REASON,
    GOAL_2,
    GOAL_6,
    GOAL_13,
    NO_SCORE,
    NOT_A_REPORT,
    TARGET_2_4,
    TARGET_6_4,
    TARGET_6_5,
    TARGET_13_1,
)
from aabflow.services.metrics import REGISTRY, mv

# PlanFacts default when the run has no stored quantization bound.
_DEFAULT_QUANTUM_KG = 0.1

Index = dict[tuple[str, str | None], MetricValue]


class Term(StrictModel):
    role: Literal["numerator", "denominator", "difference", "component"]
    label: str
    metric_id: str | None = None
    definition_id: str | None = None
    value: float | None
    unit: str
    status: MetricStatus
    run_id: str | None = None
    reason: str | None = None
    formula: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class SdgCard(StrictModel):
    card: Literal["SDG 2.4", "SDG 6.4/6.5", "SDG 13.1"]
    official_target_text: str
    target_url: str
    official_indicator: Literal[False] = False
    interpretation: str
    status: MetricStatus
    reason: str | None = None
    formula: str
    formulas: dict[str, str]
    numerator: Term | None = None
    denominator: Term | None = None
    difference_from_typical: Term | None = None
    metrics: list[str]
    values: list[dict[str, Any]]
    limitations: list[str]
    run_id: str
    baseline_run_id: str | None = None
    run_ids: list[str]
    source_records: list[str]
    crop: str | None = None


class FieldChange(StrictModel):
    field_id: str
    production_kg: float | None
    baseline_production_kg: float | None = None
    delta_kg: float | None = None
    unit: Literal["kg"] = "kg"
    status: MetricStatus
    reason: str | None = None
    run_id: str
    baseline_run_id: str | None = None
    definition_id: str
    crop: str | None = None
    causal: bool = False


class FieldChangeSummary(StrictModel):
    unit: Literal["kg"] = "kg"
    quantum_kg: float
    fields_worse_off: int
    fields_better_off: int
    fields_unchanged: int
    fields_not_comparable: int


class Co2Estimate(StrictModel):
    status: Literal[MetricStatus.not_estimated] = MetricStatus.not_estimated
    value: None = None
    unit: None = None
    reason: str
    official_indicator: Literal[False] = False


class ImpactResponse(StrictModel):
    available: bool
    run_id: str
    reason: str | None = None
    baseline_run_id: str | None = None
    compatible: bool | None = None
    compatibility_label: str | None = None
    cards: list[SdgCard] = Field(default_factory=list)
    distribution: list[FieldChange] = Field(default_factory=list)
    field_change_summary: FieldChangeSummary
    co2: Co2Estimate


def co2_estimate() -> Co2Estimate:
    return Co2Estimate(reason=CO2_REASON)


def empty_summary() -> FieldChangeSummary:
    return FieldChangeSummary(
        quantum_kg=_DEFAULT_QUANTUM_KG,
        fields_worse_off=0,
        fields_better_off=0,
        fields_unchanged=0,
        fields_not_comparable=0,
    )


def index_metrics(metrics: list[MetricValue]) -> Index:
    return {(m.metric_id, m.field_id): m for m in metrics}


def build_impact(
    *,
    run_id: str,
    run_metrics: list[MetricValue],
    baseline_run_id: str | None = None,
    baseline_metrics: list[MetricValue] | None = None,
    compatible: bool = True,
    incompatibility_reason: str | None = None,
    stress_metrics: list[MetricValue] | None = None,
    extra_limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble three cards and the field-change distribution. Does not divide proxies again."""
    base_idx = index_metrics(baseline_metrics or [])
    run_idx = index_metrics(run_metrics)
    card_idx = dict(run_idx)
    for metric in stress_metrics or []:
        if metric.field_id is None:
            card_idx[(metric.metric_id, None)] = metric
    distribution, summary = field_changes(
        run_id=run_id,
        run_idx=run_idx,
        baseline_run_id=baseline_run_id,
        base_idx=base_idx,
        compatible=compatible,
        incompatibility_reason=incompatibility_reason,
    )
    cards = [
        _card_24(card_idx, run_id, baseline_run_id),
        _card_64(
            card_idx,
            base_idx,
            run_id,
            baseline_run_id,
            compatible,
            incompatibility_reason,
        ),
        _card_131(card_idx, run_id, baseline_run_id, extra_limitations or []),
    ]
    body = ImpactResponse(
        available=True,
        run_id=run_id,
        baseline_run_id=baseline_run_id,
        compatible=compatible if baseline_run_id else None,
        compatibility_label=None
        if baseline_run_id is None or compatible
        else incompatibility_reason,
        cards=cards,
        distribution=distribution,
        field_change_summary=summary,
        co2=co2_estimate(),
    )
    return body.model_dump(mode="json")


def field_changes(
    *,
    run_id: str,
    run_idx: Index,
    baseline_run_id: str | None,
    base_idx: Index,
    compatible: bool,
    incompatibility_reason: str | None,
) -> tuple[list[FieldChange], FieldChangeSummary]:
    run_fields = _field_production(run_idx)
    base_fields = _field_production(base_idx)
    quantum = _quantum(run_idx, len(run_fields))
    definition_id = REGISTRY["field_production_delta_kg"].definition_id
    worse = better = unchanged = skipped = 0
    rows: list[FieldChange] = []
    for field_id in sorted(set(run_fields) | set(base_fields)):
        run_m = run_fields.get(field_id)
        base_m = base_fields.get(field_id)
        production = _number(run_m)
        baseline_production = _number(base_m)
        delta, status, reason, causal = _delta(
            run_m,
            base_m,
            baseline_run_id=baseline_run_id,
            compatible=compatible,
            incompatibility_reason=incompatibility_reason,
        )
        if causal and delta is not None:
            if delta < -quantum:
                worse += 1
            elif delta > quantum:
                better += 1
            else:
                unchanged += 1
        else:
            skipped += 1
        rows.append(
            FieldChange(
                field_id=field_id,
                production_kg=production,
                baseline_production_kg=baseline_production,
                delta_kg=delta,
                status=status,
                reason=reason,
                run_id=run_id,
                baseline_run_id=baseline_run_id,
                definition_id=definition_id,
                crop=run_m.crop if run_m is not None else None,
                causal=causal,
            )
        )
    summary = FieldChangeSummary(
        quantum_kg=quantum,
        fields_worse_off=worse,
        fields_better_off=better,
        fields_unchanged=unchanged,
        fields_not_comparable=skipped,
    )
    return rows, summary


def _field_production(idx: Index) -> dict[str, MetricValue]:
    return {
        fid: metric for (mid, fid), metric in idx.items() if mid == "field_production_kg" and fid
    }


def _quantum(idx: Index, n_fields: int) -> float:
    bound = idx.get(("objective_quantization_bound_kg", None))
    if (
        n_fields > 0
        and bound is not None
        and bound.status is MetricStatus.available
        and bound.value is not None
    ):
        return bound.value / n_fields
    return _DEFAULT_QUANTUM_KG


def _number(metric: MetricValue | None) -> float | None:
    if metric is None or metric.status is not MetricStatus.available:
        return None
    return metric.value


def _delta(
    run_m: MetricValue | None,
    base_m: MetricValue | None,
    *,
    baseline_run_id: str | None,
    compatible: bool,
    incompatibility_reason: str | None,
) -> tuple[float | None, MetricStatus, str | None, bool]:
    if baseline_run_id is None:
        return (
            None,
            MetricStatus.not_applicable,
            "field-change distribution needs a baseline run",
            False,
        )
    if not compatible:
        return (
            None,
            MetricStatus.not_applicable,
            incompatibility_reason or "baseline is not a compatible comparison",
            False,
        )
    if run_m is None or base_m is None:
        return (
            None,
            MetricStatus.not_estimated,
            "stored field_production_kg is absent on one side",
            False,
        )
    if run_m.status is not MetricStatus.available or base_m.status is not MetricStatus.available:
        status = _worse_status(run_m.status, base_m.status)
        reason = run_m.reason if run_m.status is not MetricStatus.available else base_m.reason
        return None, status, reason or "field production is not available on both sides", False
    if run_m.value is None or base_m.value is None:
        return None, MetricStatus.not_estimated, "stored field production value is null", False
    return run_m.value - base_m.value, MetricStatus.available, None, True


def _worse_status(a: MetricStatus, b: MetricStatus) -> MetricStatus:
    order = (
        MetricStatus.blocked,
        MetricStatus.not_estimated,
        MetricStatus.not_applicable,
        MetricStatus.available,
    )
    return a if order.index(a) <= order.index(b) else b


def _usable(metric: MetricValue) -> MetricValue:
    if metric.status is MetricStatus.available and metric.value is None:
        return metric.model_copy(
            update={
                "status": MetricStatus.not_estimated,
                "reason": metric.reason or "stored value is null",
            }
        )
    if metric.status is not MetricStatus.available and metric.value is not None:
        return metric.model_copy(update={"value": None})
    return metric


def _stored(idx: Index, metric_id: str, run_id: str) -> MetricValue:
    found = idx.get((metric_id, None))
    if found is None:
        return mv(
            metric_id,
            run_id,
            None,
            status=MetricStatus.not_estimated,
            reason=f"stored MetricValue {metric_id} is absent",
        )
    return _usable(found)


def _present(metric: MetricValue) -> dict[str, Any]:
    return _usable(metric).model_dump(mode="json")


def _term(
    metric: MetricValue,
    *,
    role: Literal["numerator", "denominator", "difference", "component"],
    label: str,
    formula: str | None = None,
) -> Term:
    shown = _usable(metric)
    return Term(
        role=role,
        label=label,
        metric_id=shown.metric_id,
        definition_id=shown.definition_id,
        value=shown.value,
        unit=shown.unit,
        status=shown.status,
        run_id=shown.run_id,
        reason=shown.reason,
        formula=formula if formula is not None else REGISTRY[shown.metric_id].formula,
        evidence_ids=list(shown.evidence_ids),
    )


def _run_ids(run_id: str, baseline_run_id: str | None) -> list[str]:
    if baseline_run_id:
        return [run_id, baseline_run_id]
    return [run_id]


def _crop(idx: Index) -> str | None:
    metric = idx.get(("production_kg", None))
    return metric.crop if metric is not None else None


def _formulas(metric_ids: list[str]) -> dict[str, str]:
    return {mid: REGISTRY[mid].formula for mid in metric_ids if mid in REGISTRY}


def _sources(*groups: list[MetricValue]) -> list[str]:
    found: set[str] = set()
    for group in groups:
        for metric in group:
            found.update(metric.evidence_ids)
    return sorted(found)


def _shared_limits(*extra: str) -> list[str]:
    return [NO_SCORE, NOT_A_REPORT, CO2_LIMIT, *extra]


def _card_24(idx: Index, run_id: str, baseline_run_id: str | None) -> SdgCard:
    retained = _stored(idx, "sdg_2_4_production_retained_fraction", run_id)
    worst = _stored(idx, "worst_tested_production_kg", run_id)
    typical = _stored(idx, "typical_production_kg", run_id)
    production = _stored(idx, "production_kg", run_id)
    metrics = [
        retained.metric_id,
        worst.metric_id,
        typical.metric_id,
        production.metric_id,
    ]
    values = [retained, worst, typical, production]
    return SdgCard(
        card="SDG 2.4",
        official_target_text=TARGET_2_4,
        target_url=GOAL_2,
        interpretation="Model-based planning resilience, not measured food security",
        status=retained.status,
        reason=retained.reason,
        formula=REGISTRY[retained.metric_id].formula,
        formulas=_formulas(metrics),
        numerator=_term(worst, role="numerator", label="Worst tested production"),
        denominator=_term(typical, role="denominator", label="Typical-state production"),
        metrics=metrics,
        values=[_present(m) for m in values],
        limitations=_shared_limits(
            "Model-based planning resilience, not measured food security.",
            "Official indicator 2.4.1 is the proportion of agricultural area under productive "
            "and sustainable agriculture. This card does not compute that indicator.",
            "Field-change rows are stored production differences against the baseline, not a score.",
        ),
        run_id=run_id,
        baseline_run_id=baseline_run_id,
        run_ids=_run_ids(run_id, baseline_run_id),
        source_records=_sources(values),
        crop=_crop(idx),
    )


def _card_64(
    idx: Index,
    base_idx: Index,
    run_id: str,
    baseline_run_id: str | None,
    compatible: bool,
    incompatibility_reason: str | None,
) -> SdgCard:
    productivity = _stored(idx, "sdg_6_4_water_productivity_kg_m3", run_id)
    production = _stored(idx, "production_kg", run_id)
    canal = _stored(idx, "canal_source_withdrawal_m3", run_id)
    groundwater = _stored(idx, "groundwater_m3", run_id)
    entitlement = _stored(idx, "sdg_6_5_min_entitlement_fulfillment", run_id)
    change = _groundwater_change(
        run_id, groundwater, base_idx, baseline_run_id, compatible, incompatibility_reason
    )
    metrics = [
        productivity.metric_id,
        production.metric_id,
        canal.metric_id,
        groundwater.metric_id,
        change.metric_id,
        entitlement.metric_id,
    ]
    values = [productivity, production, canal, groundwater, change, entitlement]
    status = _combine([productivity.status, change.status, entitlement.status])
    reason = None
    if status is not MetricStatus.available:
        reason = next(
            (
                m.reason
                for m in (productivity, change, entitlement)
                if m.status is status and m.reason
            ),
            None,
        )
    return SdgCard(
        card="SDG 6.4/6.5",
        official_target_text=f"6.4 {TARGET_6_4} 6.5 {TARGET_6_5}",
        target_url=GOAL_6,
        interpretation=(
            "Water productivity/accounting/participation proxies, not official UN indicator scores"
        ),
        status=status,
        reason=reason,
        formula=REGISTRY[productivity.metric_id].formula,
        formulas=_formulas(metrics),
        numerator=_term(production, role="numerator", label="Modeled crop production"),
        denominator=_withdrawal_term(canal, groundwater, run_id),
        metrics=metrics,
        values=[_present(m) for m in values],
        limitations=_shared_limits(
            "Water productivity, accounting and participation proxies, not official UN indicator scores.",
            "Official indicators 6.4.1 (change in water-use efficiency), 6.4.2 (level of water stress), "
            "6.5.1 (degree of integrated water resources management) and 6.5.2 (transboundary basin "
            "area with an operational arrangement) are not computed.",
            "Withdrawal is canal source withdrawal plus groundwater. Basin-wide savings and return "
            "flows are not estimated here.",
            "Entitlement fulfillment is the stored minimum of receipt / reference allowance, not a "
            "verified legal quota.",
        ),
        run_id=run_id,
        baseline_run_id=baseline_run_id,
        run_ids=_run_ids(run_id, baseline_run_id),
        source_records=_sources(values),
        crop=_crop(idx),
    )


def _groundwater_change(
    run_id: str,
    run_gw: MetricValue,
    base_idx: Index,
    baseline_run_id: str | None,
    compatible: bool,
    incompatibility_reason: str | None,
) -> MetricValue:
    if baseline_run_id is None:
        return mv(
            "sdg_6_4_groundwater_change_m3",
            run_id,
            None,
            status=MetricStatus.not_applicable,
            reason="no baseline run",
        )
    if not compatible:
        return mv(
            "sdg_6_4_groundwater_change_m3",
            run_id,
            None,
            status=MetricStatus.not_applicable,
            reason=incompatibility_reason or "baseline is not a compatible comparison",
        )
    base_gw = base_idx.get(("groundwater_m3", None))
    if base_gw is None:
        return mv(
            "sdg_6_4_groundwater_change_m3",
            run_id,
            None,
            status=MetricStatus.not_estimated,
            reason="stored baseline groundwater_m3 is absent",
        )
    base_gw = _usable(base_gw)
    if (
        run_gw.status is not MetricStatus.available
        or base_gw.status is not MetricStatus.available
        or run_gw.value is None
        or base_gw.value is None
    ):
        status = _worse_status(run_gw.status, base_gw.status)
        if status is MetricStatus.available:
            status = MetricStatus.not_estimated
        reason = run_gw.reason if run_gw.status is not MetricStatus.available else base_gw.reason
        return mv(
            "sdg_6_4_groundwater_change_m3",
            run_id,
            None,
            status=status,
            reason=reason or "groundwater change is not available",
            evidence_ids=[*run_gw.evidence_ids, *base_gw.evidence_ids],
        )
    return mv(
        "sdg_6_4_groundwater_change_m3",
        run_id,
        run_gw.value - base_gw.value,
        evidence_ids=[*run_gw.evidence_ids, *base_gw.evidence_ids],
    )


def _withdrawal_term(canal: MetricValue, groundwater: MetricValue, run_id: str) -> Term:
    formula = "canal_source_withdrawal_m3 + groundwater_m3"
    evidence = sorted(set(canal.evidence_ids) | set(groundwater.evidence_ids))
    missing = (
        canal.status is not MetricStatus.available
        or groundwater.status is not MetricStatus.available
        or canal.value is None
        or groundwater.value is None
    )
    if missing:
        status = _worse_status(canal.status, groundwater.status)
        if status is MetricStatus.available:
            status = MetricStatus.not_estimated
        reason = canal.reason if canal.status is not MetricStatus.available else groundwater.reason
        return Term(
            role="denominator",
            label="Defined withdrawal",
            value=None,
            unit="m3",
            status=status,
            run_id=run_id,
            reason=reason or "defined withdrawal is not available",
            formula=formula,
            evidence_ids=evidence,
        )
    return Term(
        role="denominator",
        label="Defined withdrawal",
        value=canal.value + groundwater.value,
        unit="m3",
        status=MetricStatus.available,
        run_id=run_id,
        formula=formula,
        evidence_ids=evidence,
    )


def _combine(statuses: list[MetricStatus]) -> MetricStatus:
    if any(status is MetricStatus.available for status in statuses):
        return MetricStatus.available
    return _worse_status(statuses[0], _worse_status(statuses[1], statuses[2]))


def _card_131(
    idx: Index,
    run_id: str,
    baseline_run_id: str | None,
    extra: list[str],
) -> SdgCard:
    primary = _primary_131(idx, run_id)
    typical = _stored(idx, "typical_production_kg", run_id)
    worst = _stored(idx, "worst_tested_production_kg", run_id)
    metrics = [primary.metric_id, typical.metric_id, worst.metric_id]
    values = [primary, typical, worst]
    difference = _difference(primary, typical)
    return SdgCard(
        card="SDG 13.1",
        official_target_text=TARGET_13_1,
        target_url=GOAL_13,
        interpretation="Scenario robustness, not a quantified disaster-risk reduction",
        status=primary.status,
        reason=primary.reason,
        formula=REGISTRY["sdg_13_1_worst_tested_production_kg"].formula,
        formulas=_formulas(
            [
                "sdg_13_1_worst_tested_production_kg",
                "typical_production_kg",
                "worst_tested_production_kg",
            ]
        ),
        numerator=_term(primary, role="numerator", label="Worst tested scenario outcome"),
        denominator=None,
        difference_from_typical=difference,
        metrics=metrics,
        values=[_present(m) for m in values],
        limitations=_shared_limits(
            "Scenario robustness within tested states, not a quantified disaster-risk reduction.",
            "Official indicators 13.1.1 (disaster-affected people), 13.1.2 (national disaster-risk "
            "strategies) and 13.1.3 (local disaster-risk strategies) are not computed.",
            "When a tested state is undeliverable the card is blocked. The worst outcome is not "
            "the minimum over the remaining cells.",
            *extra,
        ),
        run_id=run_id,
        baseline_run_id=baseline_run_id,
        run_ids=_run_ids(run_id, baseline_run_id),
        source_records=_sources(values),
        crop=_crop(idx),
    )


def _primary_131(idx: Index, run_id: str) -> MetricValue:
    explicit = idx.get(("sdg_13_1_worst_tested_production_kg", None))
    worst = idx.get(("worst_tested_production_kg", None))
    if explicit is not None:
        explicit = _usable(explicit)
        if explicit.status is MetricStatus.blocked:
            return explicit
        if worst is not None and _usable(worst).status is MetricStatus.blocked:
            blocked = _usable(worst)
            return mv(
                "sdg_13_1_worst_tested_production_kg",
                run_id,
                None,
                status=MetricStatus.blocked,
                reason=blocked.reason or explicit.reason,
                evidence_ids=blocked.evidence_ids,
            )
        return explicit
    if worst is not None and _usable(worst).status is MetricStatus.blocked:
        blocked = _usable(worst)
        return mv(
            "sdg_13_1_worst_tested_production_kg",
            run_id,
            None,
            status=MetricStatus.blocked,
            reason=blocked.reason,
            evidence_ids=blocked.evidence_ids,
        )
    if worst is not None:
        return mv(
            "sdg_13_1_worst_tested_production_kg",
            run_id,
            None,
            status=MetricStatus.not_applicable,
            reason="needs a multi-state stress or robust evaluation",
        )
    return mv(
        "sdg_13_1_worst_tested_production_kg",
        run_id,
        None,
        status=MetricStatus.not_estimated,
        reason="stored MetricValue sdg_13_1_worst_tested_production_kg is absent",
    )


def _difference(worst: MetricValue, typical: MetricValue) -> Term:
    formula = "sdg_13_1_worst_tested_production_kg - typical_production_kg"
    label = "Difference from the typical-case plan"
    if worst.status is not MetricStatus.available or worst.value is None:
        return Term(
            role="difference",
            label=label,
            metric_id="sdg_13_1_worst_tested_production_kg",
            definition_id=REGISTRY["sdg_13_1_worst_tested_production_kg"].definition_id,
            value=None,
            unit="kg",
            status=worst.status,
            run_id=worst.run_id,
            reason=worst.reason or "worst tested production is not available",
            formula=formula,
            evidence_ids=list(worst.evidence_ids),
        )
    if typical.status is not MetricStatus.available or typical.value is None:
        return Term(
            role="difference",
            label=label,
            metric_id="typical_production_kg",
            definition_id=typical.definition_id,
            value=None,
            unit="kg",
            status=typical.status
            if typical.status is not MetricStatus.available
            else MetricStatus.not_estimated,
            run_id=typical.run_id,
            reason=typical.reason or "typical-state production is not available",
            formula=formula,
            evidence_ids=list(typical.evidence_ids),
        )
    return Term(
        role="difference",
        label=label,
        value=worst.value - typical.value,
        unit="kg",
        status=MetricStatus.available,
        run_id=worst.run_id,
        formula=formula,
        evidence_ids=sorted(set(worst.evidence_ids) | set(typical.evidence_ids)),
    )
