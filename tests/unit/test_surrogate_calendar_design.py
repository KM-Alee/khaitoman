"""Regression: leap-year calendar coverage keeps analog weather in its original split.

Weather metadata below is a labelled TEST FIXTURE; no crop runs or model fitting.
"""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pandas as pd

from aabflow.domain.schemas import Crop
from aabflow.science import crop_profiles, scenarios
from aabflow.surrogate.training import build_calendar_design, refresh_release_design, split_manifest


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
    manifest = split_manifest(
        pd.DataFrame(
            {"year": [r.year_label for r in rows], "weather_source": [r.source for r in rows]}
        ),
        Crop.wheat,
    )
    assert manifest["test_year"] == "2024-25"
    assert manifest["development_years"] == ["2021-22"]
    assert "2027-28" not in manifest["development_years"]
    assert all(season.planting_date <= d <= season.sim_end for r in rows for d, _ in r.schedule)
    original = deepcopy(rows)
    refresh_release_design(rows, Crop.wheat, manifest["test_year"])
    assert [r for r in rows if r.year_label != manifest["test_year"]] == [
        r for r in original if r.year_label != manifest["test_year"]
    ]
    assert any(
        r.schedule != old.schedule
        for r, old in zip(rows, original, strict=True)
        if r.year_label == manifest["test_year"]
    )
    repeated = deepcopy(original)
    refresh_release_design(repeated, Crop.wheat, manifest["test_year"])
    assert repeated == rows


def test_split_uses_common_untouched_year_without_later_training():
    # TEST FIXTURE: discovery extends beyond both pilot archives.
    rows = [
        (source, year)
        for source in ("discovery", "pilot-a", "pilot-b")
        for year in ("2022-23", "2023-24", "2024-25")
    ]
    rows.append(("discovery", "2025-26"))
    manifest = split_manifest(pd.DataFrame(rows, columns=["weather_source", "year"]), Crop.wheat)
    assert manifest["test_year"] == "2024-25"
    assert manifest["development_years"] == ["2022-23", "2023-24"]
    assert manifest["excluded_newer_years"] == ["2025-26"]
    assert manifest["test_weather_sources"] == ["discovery", "pilot-a", "pilot-b"]


def test_split_rejects_missing_common_holdout():
    import pytest

    fixture = pd.DataFrame(
        {"weather_source": ["pilot-a", "pilot-b"], "year": ["2024-25", "2025-26"]}
    )
    with pytest.raises(ValueError, match="shared by every source"):
        split_manifest(fixture, Crop.wheat)
