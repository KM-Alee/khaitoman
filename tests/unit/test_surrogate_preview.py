"""Surrogate contract (T8.2-T8.4, AT11): no outcome features, domain refusal, typed preview, held-out gates.

Reads the current versioned artifacts (scripts/science_train_surrogate.py).
"""

import json
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aabflow.config import DATA_DIR
from aabflow.domain.schemas import Crop
from aabflow.surrogate.domain import latest_version
from aabflow.surrogate.features import feature_names
from aabflow.surrogate.prediction import OUT_OF_DOMAIN_MESSAGE, preview

MODEL_VERSION = latest_version()
MODEL = DATA_DIR / "models" / MODEL_VERSION
LEAKY = ("yield", "biomass", "harvest", "canopy", "stress", "transp", "hi_", "dry", "fresh")


@pytest.fixture(scope="module", autouse=True)
def _artifacts():
    assert (MODEL / "evaluation.json").exists(), (
        "train the surrogate first (scripts/science_train_surrogate.py)"
    )


def req(**kw):
    planting = date(2026, 11, 15)
    base = {
        "crop_profile_id": "wheat-punjab-gdd-v1",
        "soil_profile_id": "aquacrop-siltloam-pct50",
        "application_efficiency": 0.6,
        "season_id": "wheat-rabi-2026-27",
        "weather_scenario_id": "typical",
        "schedule": [
            {"date": (planting + timedelta(days=d)).isoformat(), "gross_depth_mm": 50.0}
            for d in range(10, 110, 14)
        ],
    }
    base.update(kw)
    return base


@pytest.mark.parametrize("crop", [Crop.wheat, Crop.cotton])
def test_features_exclude_outcomes(crop):
    for name in feature_names(crop):
        assert not any(t in name for t in LEAKY), name


def test_evaluation_used_whole_year_holdout_and_passed():
    for crop in ("wheat", "cotton"):
        ev = json.loads((MODEL / f"evaluation-{crop}.json").read_text())
        man = ev["split_manifest"]
        assert man["fixed_before_fitting"] and man["test_year"] not in man["development_years"]
        assert len(ev["loyo_cv"]["folds"]) == len(man["development_years"])
        assert len(ev["decision_regret"]) >= 10
        assert ev["test"]["mae_kg_ha"] < ev["baseline_test"]["mae_kg_ha"]
        assert ev["passed"] is True and all(ev["gate_results"].values())
        folds = ev["loyo_cv"]["folds"]
        assert ev["prediction_bias_correction_kg_ha"] == pytest.approx(
            -np.average([f["bias_kg_ha"] for f in folds], weights=[f["n"] for f in folds])
        )
        assert ev["split_manifest"]["test_schedule_design_seed"] == "release-audit-v7"
        choice = ev["architecture_development_comparison"]
        assert choice["selected"] == min(choice["candidates"], key=choice["candidates"].get)
        frame = pd.read_parquet(MODEL / ev["artifacts"]["training_data"])
        fitting = frame[
            frame.year.isin(man["development_years"]) & (frame.family != man["holdout_family"])
        ]
        test = frame[frame.year == man["test_year"]]
        assert not set(fitting.experiment_hash) & set(test.experiment_hash)
        assert len(fitting) == ev["samples"]["fit_pool"]
        assert set(test.weather_source) == set(man["test_weather_sources"])
        assert max(fitting.year) < man["test_year"]
        assert {"pilot-a", "pilot-b"} <= set(ev["test_by_source"])
        for source, metrics in ev["test_by_source"].items():
            assert metrics["year"] == ev["split_manifest"]["test_year"]
            assert metrics["test"]["n"] > 0
            assert len(metrics["test_by_soil"]) == 3
            assert metrics["test_holdout_family"]["n"] > 0
            assert metrics["dev_holdout_family"]["n"] > 0
            assert metrics["test_ranking"]["contexts"] >= 6
            assert len(metrics["decision_regret"]) >= 10
            assert all(f["weather_source"] == source for f in metrics["decision_regret"])
            assert all(metrics["gate_results"].values())


def test_preview_typed_in_domain_and_fast():
    preview(req())  # model load
    t = time.perf_counter()
    pv = preview(req())
    assert (time.perf_counter() - t) < 0.3  # PRD §11.1: <= 300 ms backend after model load
    assert pv.estimate_kind == "surrogate_preview" and pv.domain_status == "in_domain"
    assert pv.estimated_yield_kg_ha and pv.estimated_yield_kg_ha > 0 and pv.message is None
    assert pv.model_version == MODEL_VERSION and pv.evaluation_reference.endswith(
        "evaluation-wheat.json"
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        (
            {"schedule": [{"date": "2026-12-01", "gross_depth_mm": 200.0}]},
            "extreme irrigation depth",
        ),
        ({"soil_profile_id": "aquacrop-clayloam-pct50"}, "soil class"),
        ({"application_efficiency": 0.95}, "app_eff"),
    ],
)
def test_out_of_domain_refuses_estimate(change, reason):
    pv = preview(req(**change))
    assert pv.domain_status == "out_of_domain" and pv.estimated_yield_kg_ha is None
    assert pv.message == OUT_OF_DOMAIN_MESSAGE
    assert any(reason in r for r in pv.domain_reasons), pv.domain_reasons
