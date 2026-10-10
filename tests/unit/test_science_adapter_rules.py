"""Adapter input rules and experiment hashing that need no crop run (T5.2, T3.6)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from aabflow.domain.schemas import SoilProfile
from aabflow.science import soils
from aabflow.science.adapter import (
    CropAdapterError,
    CropSimulatorAdapter,
    IrrigationAuditError,
    PostTerminationError,
    audit_daily_irrigation,
    schedule_frame,
)
from aabflow.science.experiments import crop_experiment_hash, make_experiment

SHA = "1" * 64
SOIL = "aquacrop-siltloam-pct50"


def exp(schedule, eff=0.6):
    return make_experiment(
        "wheat-punjab-gdd-v1",
        SOIL,
        "typical",
        SHA,
        date(2026, 11, 1),
        date(2027, 5, 31),
        eff,
        schedule,
    )


def test_events_same_day_aggregate_and_hash_equal():
    a = exp([(date(2026, 12, 10), 40.0), (date(2026, 12, 10), 35.0)])
    b = exp([(date(2026, 12, 10), 75.0)])
    f = schedule_frame(a)
    assert list(f.columns) == ["Date", "Depth"] and f.Depth.tolist() == [75.0]
    assert crop_experiment_hash(a) == crop_experiment_hash(b)


def test_hash_sensitive_to_model_inputs():
    base = exp([(date(2026, 12, 10), 75.0)])
    assert crop_experiment_hash(base) != crop_experiment_hash(exp([(date(2026, 12, 11), 75.0)]))
    assert crop_experiment_hash(base) != crop_experiment_hash(
        exp([(date(2026, 12, 10), 75.0)], eff=0.75)
    )
    other_weather = base.model_copy(update={"weather_sha256": "2" * 64})
    assert crop_experiment_hash(base) != crop_experiment_hash(other_weather)
    label_only = base.model_copy(update={"weather_scenario_id": "dry"})
    assert crop_experiment_hash(base) == crop_experiment_hash(label_only)  # label, not content


def test_empty_schedule_is_typed_frame():
    f = schedule_frame(exp([]))
    assert (
        len(f) == 0 and str(f.Date.dtype).startswith("datetime64") and f.Depth.dtype == np.float64
    )


def _weather():
    d = pd.date_range("2026-11-01", "2027-05-31", freq="D")
    return pd.DataFrame(
        {"Date": d, "MinTemp": 8.0, "MaxTemp": 22.0, "Precipitation": 0.0, "ReferenceET": 3.0}
    )


@pytest.mark.parametrize(
    "schedule,match",
    [
        ([(date(2026, 11, 5), 50.0)], "outside the active crop interval"),  # before 15 Nov planting
        ([(date(2026, 12, 10), 200.0)], "exceeds the declared field application limit"),
        (
            [(date(2026, 12, 1) + pd.Timedelta(days=7 * i), 140.0) for i in range(9)],
            "seasonal depth",
        ),
    ],
)
def test_inadmissible_schedules_rejected_before_engine(schedule, match):
    with pytest.raises(CropAdapterError, match=match):
        CropSimulatorAdapter().evaluate(
            exp([(d.date() if hasattr(d, "date") else d, v) for d, v in schedule]), _weather()
        )


def test_audit_detects_clipping_and_post_termination():
    dates = pd.date_range("2026-12-01", periods=4, freq="D")
    audit_daily_irrigation(dates, np.array([0, 75, 0, 0.0]), np.array([0, 75, 0, 0.0]))
    with pytest.raises(IrrigationAuditError, match="clipped"):
        audit_daily_irrigation(dates, np.array([0, 25, 0, 0.0]), np.array([0, 75, 0, 0.0]))
    with pytest.raises(PostTerminationError) as ei:
        audit_daily_irrigation(dates, np.zeros(4), np.zeros(4), unapplied_after_mm=50.0)
    assert ei.value.last_day == date(2026, 12, 4)


def test_soil_profiles_validated():
    assert soils.parse_initial_water("pct_taw:50") == ("Pct", [50.0])
    assert soils.parse_initial_water("FC") == ("Prop", ["FC"])
    with pytest.raises(soils.SoilProfileError):
        soils.parse_initial_water("half")
    with pytest.raises(soils.SoilProfileError):
        soils.validate_soil(
            SoilProfile(soil_profile_id="x", engine_soil_type="Peat", archetype="x")
        )
