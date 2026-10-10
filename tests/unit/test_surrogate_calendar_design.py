"""Regression: leap-year calendar coverage keeps analog weather in its original split.

Weather metadata below is a labelled TEST FIXTURE; no crop runs or model fitting.
"""

from datetime import date
from types import SimpleNamespace

import pandas as pd

from aabflow.domain.schemas import Crop
from aabflow.science import crop_profiles, scenarios
from aabflow.surrogate.training import build_calendar_design, split_manifest


def test_mapped_weather_keeps_held_out_source_year(monkeypatch):
    season = crop_profiles.season("wheat-rabi-2027-28")  # includes 29 February 2028
    monkeypatch.setattr(crop_profiles, "SEASONS", {season.season_id: season})
    weather = [
        SimpleNamespace(analog_season_start=date(2021, 11, 1), transformed_sha256="a" * 64),
        SimpleNamespace(analog_season_start=date(2024, 11, 1), transformed_sha256="b" * 64),
    ]
    monkeypatch.setattr(scenarios, "load_weather_scenarios", lambda sid, pid: weather)
    rows = build_calendar_design(Crop.wheat, "TEST FIXTURE")
    assert rows and {r.weather_sha for r in rows} == {"a" * 64, "b" * 64}
    assert all(r.planting == date(2027, 11, 15) and r.sim_end == date(2028, 5, 31) for r in rows)
    assert all(r.calendar_season_id == season.season_id for r in rows)
    assert all(r.year_label == "2024-25" for r in rows if r.weather_sha == "b" * 64)
    assert all(r.year_label == "2021-22" for r in rows if r.weather_sha == "a" * 64)
    manifest = split_manifest(pd.DataFrame({"year": [r.year_label for r in rows]}), Crop.wheat)
    assert manifest["test_year"] == "2024-25"
    assert manifest["development_years"] == ["2021-22"]
    assert "2027-28" not in manifest["development_years"]
    assert all(season.planting_date <= d <= season.sim_end for r in rows for d, _ in r.schedule)
