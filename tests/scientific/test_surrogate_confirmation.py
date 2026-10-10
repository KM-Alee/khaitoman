"""AT11: a preview is exact-confirmed through run_experiment before final use (real AquaCrop)."""

from datetime import date, timedelta

import pytest

from aabflow.surrogate.prediction import confirm

pytestmark = pytest.mark.scientific


def test_exact_confirmation_replaces_preview():
    planting = date(2026, 11, 15)
    req = {
        "crop_profile_id": "wheat-punjab-gdd-v1",
        "soil_profile_id": "aquacrop-loam-pct50",
        "application_efficiency": 0.75,
        "season_id": "wheat-rabi-2026-27",
        "weather_scenario_id": "dry",
        "schedule": [
            {"date": (planting + timedelta(days=d)).isoformat(), "gross_depth_mm": 45.0}
            for d in range(7, 112, 10)
        ],
    }
    outcome, pv, diff = confirm(req)
    assert pv.estimate_kind == "surrogate_preview" and pv.domain_status == "in_domain"
    assert outcome.has_finished and outcome.seasonal_irrigation_mm == pytest.approx(45.0 * 11)
    assert diff == pytest.approx(pv.estimated_yield_kg_ha - outcome.yield_kg_ha)
    assert (
        abs(diff) < 0.25 * outcome.yield_kg_ha
    )  # sanity, not the gate (gates live in evaluation.json)
