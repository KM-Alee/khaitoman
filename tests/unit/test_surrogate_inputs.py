"""Labelled input fixtures: timing resolution and failed crop execution safeguards."""

from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from aabflow.domain.schemas import Crop
from aabflow.science import crop_profiles, soils
from aabflow.surrogate import training
from aabflow.surrogate.features import compute_features


def test_equal_monthly_totals_preserve_application_timing():
    crop = crop_profiles.season_crop(Crop.cotton)
    soil = soils.soil("aquacrop-siltloam-pct50")
    start = crop.planting_date - timedelta(days=14)
    weather = pd.DataFrame(
        {
            "Date": pd.date_range(start, periods=220),
            "Precipitation": 0.0,
            "ReferenceET": 5.0,
            "MaxTemp": 34.0,
            "MinTemp": 20.0,
        }
    )
    early = compute_features(
        crop, soil, 0.6, [(crop.planting_date + timedelta(days=7), 50)], weather, start
    )
    late = compute_features(
        crop, soil, 0.6, [(crop.planting_date + timedelta(days=21), 50)], weather, start
    )
    assert early["irr_total_mm"] == late["irr_total_mm"]
    assert early["w0_net_mm"] > late["w0_net_mm"]
    assert early["w1_net_mm"] < late["w1_net_mm"]


def test_failed_exact_experiment_cannot_disappear_from_design(monkeypatch):
    row = SimpleNamespace()
    monkeypatch.setattr(training, "_experiment", lambda r: "TEST-FIXTURE")
    monkeypatch.setattr(training, "crop_experiment_hash", lambda e: "TEST-FIXTURE")
    monkeypatch.setattr(
        training,
        "run_batch",
        lambda *args, **kw: SimpleNamespace(outcomes={}, failed={"TEST-FIXTURE": "engine error"}),
    )
    with pytest.raises(RuntimeError, match="engine error"):
        training.execute_design([row])
