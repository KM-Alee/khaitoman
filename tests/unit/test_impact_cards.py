"""SDG cards are assembled from stored MetricValues (PRD §8.5, T7.5)."""

from __future__ import annotations

import math

from aabflow.domain.schemas import MetricStatus, MetricValue
from aabflow.services.impact.cards import build_impact
from aabflow.services.metrics import mv

RUN = "run_plan"
BASE = "run_base"
BLOCKED = "at least one tested state is undeliverable for this plan"


def metric(metric_id: str, value, **kwargs) -> MetricValue:
    run_id = kwargs.pop("run_id", RUN)
    return mv(metric_id, run_id, value, **kwargs)


def card(body: dict, name: str) -> dict:
    return next(item for item in body["cards"] if item["card"] == name)


def value_of(item: dict, metric_id: str):
    return next(row for row in item["values"] if row["metric_id"] == metric_id)


def assert_no_score(obj) -> None:
    if isinstance(obj, dict):
        assert "score" not in obj
        assert "sdg_score" not in obj
        for child in obj.values():
            assert_no_score(child)
    elif isinstance(obj, list):
        for child in obj:
            assert_no_score(child)


def _numbers(obj, found: list[float]) -> None:
    if isinstance(obj, dict):
        for child in obj.values():
            _numbers(child, found)
    elif isinstance(obj, list):
        for child in obj:
            _numbers(child, found)
    elif isinstance(obj, float):
        found.append(obj)


def test_three_cards_are_project_proxies_without_a_score():
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric("production_kg", 1000, crop="wheat", evidence_ids=["ev_prod"]),
            metric("sdg_2_4_production_retained_fraction", 0.5),
            metric("worst_tested_production_kg", 900),
            metric("typical_production_kg", 1000),
            metric("sdg_6_4_water_productivity_kg_m3", 1.5),
            metric("canal_source_withdrawal_m3", 400),
            metric("groundwater_m3", 100, evidence_ids=["ev_gw"]),
            metric("sdg_6_5_min_entitlement_fulfillment", 0.8),
            metric("sdg_13_1_worst_tested_production_kg", 900),
        ],
        baseline_run_id=BASE,
        baseline_metrics=[metric("groundwater_m3", 140, run_id=BASE, evidence_ids=["ev_base"])],
    )
    assert body["available"] is True
    assert [item["card"] for item in body["cards"]] == ["SDG 2.4", "SDG 6.4/6.5", "SDG 13.1"]
    urls = {"SDG 2.4": "goal2", "SDG 6.4/6.5": "goal6", "SDG 13.1": "goal13"}
    for item in body["cards"]:
        assert item["official_indicator"] is False
        assert item["official_target_text"]
        assert item["target_url"] == f"https://sdgs.un.org/goals/{urls[item['card']]}"
        assert item["formula"]
        assert item["limitations"]
        assert item["run_id"] == RUN
        assert item["baseline_run_id"] == BASE
        assert item["run_ids"] == [RUN, BASE]
        assert "0–100" in " ".join(item["limitations"]) or "0-100" in " ".join(item["limitations"])
    food = card(body, "SDG 2.4")
    assert food["numerator"]["value"] == 900
    assert food["numerator"]["unit"] == "kg"
    assert food["denominator"]["value"] == 1000
    assert food["denominator"]["unit"] == "kg"
    assert value_of(food, "sdg_2_4_production_retained_fraction")["value"] == 0.5
    water = card(body, "SDG 6.4/6.5")
    assert water["numerator"]["unit"] == "kg"
    assert water["denominator"]["unit"] == "m3"
    assert water["denominator"]["value"] == 500
    assert value_of(water, "sdg_6_4_water_productivity_kg_m3")["value"] == 1.5
    change = value_of(water, "sdg_6_4_groundwater_change_m3")
    assert change["value"] == -40
    assert change["unit"] == "m3"
    assert change["status"] == "available"
    robust = card(body, "SDG 13.1")
    assert robust["status"] == "available"
    assert robust["difference_from_typical"]["value"] == -100
    assert robust["difference_from_typical"]["unit"] == "kg"
    assert body["co2"]["status"] == "not_estimated"
    assert body["co2"]["value"] is None
    assert body["co2"]["official_indicator"] is False
    assert_no_score(body)
    numbers: list[float] = []
    _numbers(body, numbers)
    assert all(math.isfinite(number) for number in numbers)


def test_displayed_proxy_is_the_stored_metric_not_a_recomputation():
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric("sdg_2_4_production_retained_fraction", 0.5),
            metric("worst_tested_production_kg", 900),
            metric("typical_production_kg", 1000),
            metric("production_kg", 1000, crop="cotton"),
            metric("sdg_6_4_water_productivity_kg_m3", 1.5),
            metric("canal_source_withdrawal_m3", 50),
            metric("groundwater_m3", 50),
        ],
    )
    food = card(body, "SDG 2.4")
    assert value_of(food, "sdg_2_4_production_retained_fraction")["value"] == 0.5
    water = card(body, "SDG 6.4/6.5")
    assert value_of(water, "sdg_6_4_water_productivity_kg_m3")["value"] == 1.5
    assert water["denominator"]["value"] == 100


def test_card_13_1_blocked_when_tested_state_undeliverable():
    stray = metric(
        "sdg_13_1_worst_tested_production_kg", None, status=MetricStatus.blocked, reason=BLOCKED
    )
    dumped = stray.model_dump()
    dumped["value"] = 77
    hostile = MetricValue.model_validate(dumped)
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            hostile,
            metric("worst_tested_production_kg", None, status=MetricStatus.blocked, reason=BLOCKED),
            metric(
                "sdg_2_4_production_retained_fraction",
                None,
                status=MetricStatus.blocked,
                reason=BLOCKED,
            ),
            metric("typical_production_kg", 1000),
            metric("production_kg", 400, crop="wheat"),
        ],
    )
    robust = card(body, "SDG 13.1")
    assert robust["status"] == "blocked"
    assert BLOCKED in (robust["reason"] or "")
    primary = value_of(robust, "sdg_13_1_worst_tested_production_kg")
    assert primary["value"] is None
    assert primary["status"] == "blocked"
    assert robust["difference_from_typical"]["value"] is None
    assert robust["difference_from_typical"]["status"] == "blocked"
    assert all(row["value"] != 77 for row in robust["values"])
    assert all(row["value"] != 400 for row in robust["values"])
    food = card(body, "SDG 2.4")
    assert food["status"] == "blocked"
    assert value_of(food, "sdg_2_4_production_retained_fraction")["value"] is None


def test_stress_blocked_metric_overrides_single_state_not_applicable():
    blocked = metric(
        "sdg_13_1_worst_tested_production_kg",
        None,
        status=MetricStatus.blocked,
        reason=BLOCKED,
    )
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric(
                "sdg_13_1_worst_tested_production_kg",
                None,
                status=MetricStatus.not_applicable,
                reason="needs a multi-state stress or robust evaluation",
            ),
            metric("typical_production_kg", 800),
            metric("production_kg", 250),
        ],
        stress_metrics=[blocked],
    )
    robust = card(body, "SDG 13.1")
    assert robust["status"] == "blocked"
    assert value_of(robust, "sdg_13_1_worst_tested_production_kg")["value"] is None
    assert robust["difference_from_typical"]["value"] is None


def test_single_state_13_1_is_not_applicable():
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric(
                "worst_tested_production_kg",
                500,
                reason="single evaluated state: the minimum is that state's production",
            ),
            metric("typical_production_kg", 500),
            metric(
                "sdg_13_1_worst_tested_production_kg",
                None,
                status=MetricStatus.not_applicable,
                reason="needs a multi-state stress or robust evaluation",
            ),
        ],
    )
    robust = card(body, "SDG 13.1")
    assert robust["status"] == "not_applicable"
    assert value_of(robust, "sdg_13_1_worst_tested_production_kg")["value"] is None
    assert robust["difference_from_typical"]["value"] is None


def test_missing_inputs_are_not_estimated_and_not_zero():
    body = build_impact(run_id=RUN, run_metrics=[metric("production_kg", 10, crop="wheat")])
    food = card(body, "SDG 2.4")
    assert food["status"] == "not_estimated"
    assert value_of(food, "sdg_2_4_production_retained_fraction")["value"] is None
    water = card(body, "SDG 6.4/6.5")
    assert value_of(water, "sdg_6_4_water_productivity_kg_m3")["value"] is None
    assert value_of(water, "sdg_6_4_water_productivity_kg_m3")["status"] == "not_estimated"
    assert value_of(water, "sdg_6_4_groundwater_change_m3")["status"] == "not_applicable"
    robust = card(body, "SDG 13.1")
    assert robust["status"] == "not_estimated"
    assert value_of(robust, "sdg_13_1_worst_tested_production_kg")["value"] is None


def test_zero_withdrawal_stays_not_applicable():
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric("production_kg", 100, crop="wheat"),
            metric(
                "sdg_6_4_water_productivity_kg_m3",
                None,
                status=MetricStatus.not_applicable,
                reason="zero withdrawal",
            ),
            metric("canal_source_withdrawal_m3", 0),
            metric("groundwater_m3", 0),
            metric("sdg_6_5_min_entitlement_fulfillment", 1),
        ],
    )
    water = card(body, "SDG 6.4/6.5")
    stored = value_of(water, "sdg_6_4_water_productivity_kg_m3")
    assert stored["status"] == "not_applicable"
    assert stored["value"] is None
    assert water["denominator"]["value"] == 0
    assert water["status"] == "available"
    numbers: list[float] = []
    _numbers(body, numbers)
    assert numbers
    assert all(math.isfinite(number) for number in numbers)


def test_field_change_distribution_uses_stored_production():
    run_metrics = [
        metric("objective_quantization_bound_kg", 3),
        metric("field_production_kg", 8, field_id="f1", crop="wheat"),
        metric("field_production_kg", 10, field_id="f2", crop="wheat"),
        metric("field_production_kg", 12, field_id="f3", crop="wheat"),
    ]
    base_metrics = [
        metric("field_production_kg", 10, run_id=BASE, field_id="f1", crop="wheat"),
        metric("field_production_kg", 10, run_id=BASE, field_id="f2", crop="wheat"),
        metric("field_production_kg", 10, run_id=BASE, field_id="f3", crop="wheat"),
    ]
    body = build_impact(
        run_id=RUN,
        run_metrics=run_metrics,
        baseline_run_id=BASE,
        baseline_metrics=base_metrics,
    )
    rows = {row["field_id"]: row for row in body["distribution"]}
    assert rows["f1"]["delta_kg"] == -2
    assert rows["f1"]["production_kg"] == 8
    assert rows["f1"]["baseline_production_kg"] == 10
    assert rows["f1"]["causal"] is True
    assert rows["f1"]["unit"] == "kg"
    assert rows["f2"]["delta_kg"] == 0
    assert rows["f3"]["delta_kg"] == 2
    summary = body["field_change_summary"]
    assert summary["quantum_kg"] == 1
    assert summary["fields_worse_off"] == 1
    assert summary["fields_unchanged"] == 1
    assert summary["fields_better_off"] == 1
    assert summary["fields_not_comparable"] == 0


def test_incompatible_baseline_does_not_invent_changes():
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric("field_production_kg", 12, field_id="f1"),
            metric("groundwater_m3", 4),
        ],
        baseline_run_id=BASE,
        baseline_metrics=[
            metric("field_production_kg", 10, run_id=BASE, field_id="f1"),
            metric("groundwater_m3", 9, run_id=BASE),
        ],
        compatible=False,
        incompatibility_reason="non-matched comparison: differences are not causal",
    )
    row = body["distribution"][0]
    assert row["production_kg"] == 12
    assert row["delta_kg"] is None
    assert row["status"] == "not_applicable"
    assert row["causal"] is False
    change = value_of(card(body, "SDG 6.4/6.5"), "sdg_6_4_groundwater_change_m3")
    assert change["value"] is None
    assert change["status"] == "not_applicable"
    assert body["compatible"] is False


def test_missing_field_outcome_is_not_a_zero_change():
    body = build_impact(
        run_id=RUN,
        run_metrics=[
            metric(
                "field_production_kg",
                None,
                field_id="f9",
                status=MetricStatus.not_estimated,
                reason="a selected field lacks an exact crop outcome",
            )
        ],
        baseline_run_id=BASE,
        baseline_metrics=[metric("field_production_kg", 5, run_id=BASE, field_id="f9")],
    )
    row = body["distribution"][0]
    assert row["delta_kg"] is None
    assert row["production_kg"] is None
    assert row["status"] == "not_estimated"
    assert row["delta_kg"] != 0
