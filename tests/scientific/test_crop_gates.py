"""T5.4 scientific smoke gates 2-7 and AT02 evidence (real AquaCrop, real ERA5 weather).

Weather: the science discovery-point Open-Meteo/ERA5 series published under
data/libraries/weather/series (scripts/science_publish.py). Runs execute in an
isolated data dir so tests never mutate the shared experiment cache.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from aabflow.config import DATA_DIR as REPO_DATA
from aabflow.science import paths
from aabflow.science.adapter import (
    RESULT_COLUMNS,
    CropAdapterError,
    IrrigationAuditError,
    audit_daily_irrigation,
)
from aabflow.science.experiments import (
    experiment_dir,
    load_trajectory,
    make_experiment,
    run_experiment,
)
from aabflow.science.scenarios import DISCOVERY_SERIES_ID
from aabflow.science.weather import slice_window, store_weather

pytestmark = pytest.mark.scientific

SOIL = "aquacrop-siltloam-pct50"
WHEAT = "wheat-punjab-gdd-v1"
COTTON = "cotton-punjab-v1"
W_START, W_END = date(2023, 11, 1), date(2024, 5, 31)  # complete historical rabi 2023-24
C_START, C_END = date(2023, 4, 17), date(2023, 12, 15)  # complete historical kharif 2023


@pytest.fixture(scope="module")
def series() -> pd.DataFrame:
    p = REPO_DATA / "libraries" / "weather" / "series" / DISCOVERY_SERIES_ID / "normalized.parquet"
    assert p.exists(), "run scripts/science_publish.py first (fetches the ERA5 archive)"
    df = pd.read_parquet(p)
    df["Date"] = pd.to_datetime(df["Date"]).astype("datetime64[ns]")
    return df


@pytest.fixture
def sci(tmp_path, monkeypatch, series):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    w = store_weather(slice_window(series, W_START, W_END))[0]
    c = store_weather(slice_window(series, C_START, C_END))[0]
    return {"wheat": w, "cotton": c, "dir": tmp_path}


def wheat(sci, sched, eff=0.6):
    return run_experiment(
        make_experiment(WHEAT, SOIL, "hist-2023-24", sci["wheat"], W_START, W_END, eff, sched)
    )


def cotton(sci, sched, eff=0.6):
    return run_experiment(
        make_experiment(COTTON, SOIL, "hist-2023", sci["cotton"], C_START, C_END, eff, sched)
    )


WHEAT_A = [(date(2023, 12, 5), 75.0), (date(2024, 1, 15), 75.0), (date(2024, 2, 20), 75.0)]
WHEAT_B = [
    (date(2023, 11, 25), 50.0),
    (date(2023, 12, 20), 50.0),
    (date(2024, 1, 25), 60.0),
    (date(2024, 2, 15), 60.0),
    (date(2024, 3, 5), 60.0),
]
COTTON_A = [(date(2023, 5, 20), 75.0), (date(2023, 6, 15), 75.0), (date(2023, 7, 10), 75.0)]
COTTON_B = [
    (date(2023, 5, 15), 60.0),
    (date(2023, 6, 5), 60.0),
    (date(2023, 6, 25), 60.0),
    (date(2023, 7, 15), 60.0),
    (date(2023, 8, 10), 60.0),
    (date(2023, 9, 5), 60.0),
]


def _check_treatments(outs, seasons_mm):
    for o, mm in zip(outs, seasons_mm, strict=True):
        assert o.has_finished and o.actual_harvest_date is not None
        assert np.isfinite(o.yield_kg_ha) and o.yield_kg_ha >= 0
        assert o.seasonal_irrigation_mm == pytest.approx(mm)
        tr = load_trajectory(o)
        assert tr["gross_irrigation_mm"].sum() == pytest.approx(mm)
        assert np.isfinite(tr.select_dtypes("number").to_numpy()).all()
        raw = pd.read_parquet(experiment_dir(o.experiment_hash) / "raw_simulation_results.parquet")
        assert list(raw.columns) == RESULT_COLUMNS
        assert o.yield_kg_ha == pytest.approx(float(raw["Dry yield (tonne/ha)"].iloc[0]) * 1000)
        assert o.raw_output_refs and all(
            (paths.experiments_dir() / ref).is_file() for ref in o.raw_output_refs
        )
    assert len({round(o.yield_kg_ha, 3) for o in outs}) == len(outs)  # treatments actually differ
    assert len({o.experiment_hash for o in outs}) == len(outs)


def test_at02_gate2_wheat_three_treatments(sci):
    outs = [wheat(sci, []), wheat(sci, WHEAT_A), wheat(sci, WHEAT_B)]
    _check_treatments(outs, [0, 225, 280])
    rain, a, b = outs
    # explained response: irrigation relieves water stress from a 50% TAW start (not assumed monotone)
    assert a.yield_kg_ha > rain.yield_kg_ha and b.yield_kg_ha > rain.yield_kg_ha
    assert 0 < rain.yield_kg_ha < 9000 and a.yield_basis == "dry_grain"
    assert rain.actual_harvest_date <= a.actual_harvest_date  # stressed crop matures earlier


def test_at02_gate3_cotton_three_treatments(sci):
    outs = [cotton(sci, []), cotton(sci, COTTON_A), cotton(sci, COTTON_B)]
    _check_treatments(outs, [0, 225, 360])
    assert outs[2].yield_kg_ha > outs[0].yield_kg_ha
    assert outs[0].yield_basis == "dry_seed_cotton_model"
    assert all(date(2023, 9, 1) <= o.actual_harvest_date <= date(2023, 12, 15) for o in outs)


def test_gate4_above_default_cap_and_clipping_detection(sci, series):
    big = [(date(2023, 12, 5), 100.0)]  # above the package default MaxIrr = 25 mm/day
    o = wheat(sci, big)
    assert o.seasonal_irrigation_mm == pytest.approx(100.0)  # explicit MaxIrr: not clipped
    # Same schedule through the package defaults is clipped, and the audit catches it.
    from aquacrop.core import AquaCropModel
    from aquacrop.entities.crop import Crop
    from aquacrop.entities.inititalWaterContent import InitialWaterContent
    from aquacrop.entities.irrigationManagement import IrrigationManagement
    from aquacrop.entities.soil import Soil

    sched = pd.DataFrame({"Date": pd.to_datetime(["2023-12-05"]), "Depth": [100.0]})
    irr = IrrigationManagement(irrigation_method=3, Schedule=sched)
    assert irr.MaxIrr == 25.0
    w = slice_window(series, W_START, W_END)
    m = AquaCropModel(
        "2023/11/01",
        "2024/05/31",
        w[["MinTemp", "MaxTemp", "Precipitation", "ReferenceET", "Date"]],
        Soil("SiltLoam"),
        Crop("WheatGDD", planting_date="11/15"),
        InitialWaterContent(wc_type="Pct", value=[50]),
        irrigation_management=irr,
    )
    m.run_model(till_termination=True)
    applied = m.get_water_flux()["IrrDay"].to_numpy()[: len(m._clock_struct.time_span)]
    expected = np.zeros_like(applied)
    expected[(pd.Timestamp("2023-12-05") - pd.Timestamp("2023-11-01")).days] = 100.0
    assert applied.max() == pytest.approx(25.0)
    with pytest.raises(IrrigationAuditError, match="clipped"):
        audit_daily_irrigation(pd.DatetimeIndex(m._clock_struct.time_span), applied, expected)
    with pytest.raises(CropAdapterError, match="application limit"):
        wheat(sci, [(date(2023, 12, 5), 151.0)])


def test_gate5_application_efficiency_applied_once(sci):
    full = wheat(sci, WHEAT_A, eff=1.0)
    part = wheat(sci, WHEAT_A, eff=0.6)
    assert (
        full.seasonal_irrigation_mm == part.seasonal_irrigation_mm == pytest.approx(225)
    )  # gross recorded
    tf, tp = load_trajectory(full), load_trajectory(part)
    for d, depth in WHEAT_A:
        row_f = tf[tf.date == d.isoformat()].iloc[0]
        row_p = tp[tp.date == d.isoformat()].iloc[0]
        rain = row_f.precipitation_mm
        if rain == 0 and row_f.runoff_mm == 0 and row_p.runoff_mm == 0:
            assert row_f.infiltrated_mm == pytest.approx(depth)
            assert row_p.infiltrated_mm == pytest.approx(depth * 0.6)  # once, not 0.36
    assert full.yield_kg_ha >= part.yield_kg_ha


def test_gate6_out_of_season_events_fail(sci):
    with pytest.raises(CropAdapterError, match="outside the active crop interval"):
        wheat(sci, [(date(2023, 11, 5), 50.0)])  # before 15 Nov planting
    with pytest.raises(CropAdapterError, match="after crop termination|outside"):
        wheat(sci, [(date(2024, 5, 25), 50.0)])  # after maturity (early April)


def test_gate6b_empty_schedule_equals_rainfed_method(sci, series):
    o = wheat(sci, [])
    from aquacrop.core import AquaCropModel
    from aquacrop.entities.crop import Crop
    from aquacrop.entities.inititalWaterContent import InitialWaterContent
    from aquacrop.entities.irrigationManagement import IrrigationManagement
    from aquacrop.entities.soil import Soil

    w = slice_window(series, W_START, W_END)
    m = AquaCropModel(
        "2023/11/01",
        "2024/05/31",
        w[["MinTemp", "MaxTemp", "Precipitation", "ReferenceET", "Date"]],
        Soil("SiltLoam"),
        Crop("WheatGDD", planting_date="11/15"),
        InitialWaterContent(wc_type="Pct", value=[50]),
        irrigation_management=IrrigationManagement(irrigation_method=0),
    )
    m.run_model(till_termination=True)
    assert o.yield_kg_ha == pytest.approx(
        m.get_simulation_results()["Dry yield (tonne/ha)"].iloc[0] * 1000
    )


def test_gate7_raw_columns_and_yield_basis(sci):
    o = wheat(sci, WHEAT_A)
    d = experiment_dir(o.experiment_hash)
    raw = pd.read_parquet(d / "raw_simulation_results.parquet")
    assert list(raw.columns) == RESULT_COLUMNS
    assert o.yield_kg_ha == pytest.approx(
        float(raw["Dry yield (tonne/ha)"].iloc[0]) * 1000.0
    )  # once
    growth = pd.read_parquet(d / "raw_crop_growth.parquet")
    flux = pd.read_parquet(d / "raw_water_flux.parquet")
    assert {"DryYield", "biomass", "canopy_cover"} <= set(growth.columns)
    assert {"IrrDay", "Tr", "Es", "DeepPerc", "Runoff"} <= set(flux.columns)
    tr = load_trajectory(o)
    last = growth.iloc[len(tr) - 1]
    assert float(last["DryYield"]) * 1000 == pytest.approx(o.yield_kg_ha, rel=1e-6)
    assert tr.biomass_kg_ha.iloc[-1] == pytest.approx(float(last["biomass"]) * 10)
    assert tr.date.iloc[0] == "2023-11-01"  # aligned to the simulation calendar, not planting
    assert (tr.dap.iloc[:14] == 0).all()
    assert (d / "outcome.json").exists() and (d / "evidence.json").exists()


def test_cache_reuses_hash(sci):
    a = wheat(sci, WHEAT_A)
    b = wheat(sci, list(WHEAT_A))
    assert a.experiment_hash == b.experiment_hash and a.executed_at == b.executed_at


def test_batch_runner_with_warmup(sci):
    from aabflow.science.experiments import run_batch

    exps = [
        make_experiment(
            WHEAT, SOIL, "h", sci["wheat"], W_START, W_END, 0.6, [(date(2023, 12, 5), float(d))]
        )
        for d in (10, 20, 30, 40, 50, 60)
    ]
    rep = run_batch(exps, workers=2)
    assert rep.total == 6 and not rep.failed and len(rep.outcomes) == 6
    again = run_batch(exps, workers=2)
    assert again.cached == 6 and again.executed == 0
