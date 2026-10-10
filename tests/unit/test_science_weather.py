"""Weather normalization/validation and analog mapping (T2.5, T12.1 weather row). TEST FIXTURE frames."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from aabflow.science import crop_profiles
from aabflow.science.weather import (
    WeatherValidationError,
    map_analog,
    normalize_archive,
    validate_weather,
    weather_sha256,
)


def frame(start="2015-11-01", end="2016-05-31"):
    d = pd.date_range(start, end, freq="D")
    n = len(d)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "Date": d.astype("datetime64[ns]"),
            "MinTemp": rng.uniform(2, 15, n),
            "MaxTemp": rng.uniform(18, 32, n),
            "Precipitation": rng.uniform(0, 3, n),
            "ReferenceET": rng.uniform(1, 6, n),
        }
    )


def test_valid_frame_passes():
    f = frame()
    assert validate_weather(f, date(2015, 11, 1), date(2016, 5, 31)) is f


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda f: f.drop(index=10).reset_index(drop=True), "complete daily range"),
        (
            lambda f: pd.concat([f, f.iloc[[5]]]).sort_values("Date").reset_index(drop=True),
            "duplicate",
        ),
        (
            lambda f: f.assign(Precipitation=f.Precipitation.where(f.index != 3, np.nan)),
            "missing values",
        ),
        (lambda f: f.assign(ReferenceET=f.ReferenceET.where(f.index != 3, np.inf)), "nonfinite"),
        (lambda f: f.assign(MinTemp=f.MinTemp.where(f.index != 4, 40.0)), "MinTemp > MaxTemp"),
        (lambda f: f.assign(Precipitation=f.Precipitation.where(f.index != 4, -1.0)), "negative"),
        (lambda f: f.assign(MaxTemp=f.MaxTemp.where(f.index != 4, 70.0)), "physical range"),
    ],
)
def test_invalid_frames_rejected(mutate, match):
    with pytest.raises(WeatherValidationError, match=match):
        validate_weather(mutate(frame()), date(2015, 11, 1), date(2016, 5, 31))


def test_wrong_window_rejected():
    with pytest.raises(WeatherValidationError):
        validate_weather(frame(), date(2015, 10, 1), date(2016, 5, 31))


def test_normalize_archive_maps_units_and_keeps_missing():
    payload = {
        "daily_units": {
            "temperature_2m_min": "°C",
            "temperature_2m_max": "°C",
            "precipitation_sum": "mm",
            "et0_fao_evapotranspiration": "mm",
        },
        "daily": {
            "time": ["2020-01-01", "2020-01-02"],
            "temperature_2m_min": [5.0, None],
            "temperature_2m_max": [20.0, 21.0],
            "precipitation_sum": [0.0, 1.0],
            "et0_fao_evapotranspiration": [2.0, 2.1],
        },
    }
    df = normalize_archive(payload)
    assert list(df.columns) == ["Date", "MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]
    assert np.isnan(df.MinTemp.iloc[1])  # never interpolated
    with pytest.raises(WeatherValidationError, match="missing values"):
        validate_weather(df, date(2020, 1, 1), date(2020, 1, 2))
    payload["daily_units"]["precipitation_sum"] = "inch"
    with pytest.raises(WeatherValidationError, match="unit"):
        normalize_archive(payload)


def test_analog_mapping_offset_preserving_leap_rule():
    src = frame("2015-11-01", "2016-06-30")  # source season contains 29 Feb 2016
    m = map_analog(src, date(2015, 11, 1), date(2026, 11, 1), 212)
    assert len(m.weather) == 212 and m.offset_days == (date(2026, 11, 1) - date(2015, 11, 1)).days
    validate_weather(m.weather, date(2026, 11, 1), date(2027, 5, 31))
    # every original day maps to exactly one scenario day; values retained in order
    assert m.table.original_date.is_unique and m.table.scenario_date.is_unique
    np.testing.assert_array_equal(
        m.weather.Precipitation.to_numpy(), src.Precipitation.to_numpy()[:212]
    )
    assert "2016-02-29" in set(m.table.original_date)
    assert m.leap_drift_note and "source" in m.leap_drift_note
    assert m.source_sha256 != m.transformed_sha256


def test_weather_hash_is_content_based():
    a, b = frame(), frame()
    assert weather_sha256(a) == weather_sha256(b)
    b.loc[3, "Precipitation"] += 0.1
    assert weather_sha256(a) != weather_sha256(b)


def test_crop_calendars_and_windows():
    w = crop_profiles.WHEAT
    assert (
        w.engine_crop_name == "WheatGDD" and w.max_daily_irrigation_mm > 25
    )  # above package default
    s = crop_profiles.season("wheat-rabi-2026-27")
    assert s.planting_date == date(2026, 11, 15) and s.sim_start == date(2026, 11, 1)
    assert s.sim_end == date(2027, 5, 31)
    c = crop_profiles.season("cotton-kharif-2027")
    assert c.planting_date == date(2027, 5, 1) and c.crop_profile_id == "cotton-punjab-v1"
    assert crop_profiles.season("wheat-rabi-2024-25").weather_basis == "actual"
    assert crop_profiles.planting_in_window(w, date(2010, 11, 1)) == date(2010, 11, 15)
