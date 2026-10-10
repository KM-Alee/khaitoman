"""Open-Meteo normalization and T2.5 validation, including rejection cases (synthetic payloads)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from aabflow.ingestion.weather import openmeteo as om


def payload(start=date(2015, 1, 1), days=365 * 2 + 1, **override):
    """Synthetic Open-Meteo archive response (test fixture)."""
    times = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    p = {
        "latitude": 30.8, "longitude": 72.3, "elevation": 152.0, "timezone": "Asia/Karachi",
        "daily_units": {"time": "iso8601", "temperature_2m_min": "°C", "temperature_2m_max": "°C",
                        "precipitation_sum": "mm", "et0_fao_evapotranspiration": "mm"},
        "daily": {"time": times,
                  "temperature_2m_min": [10.0] * days, "temperature_2m_max": [24.0] * days,
                  "precipitation_sum": [0.0] * days, "et0_fao_evapotranspiration": [3.1] * days},
    }  # fmt: skip
    for k, v in override.items():
        p["daily"][k] = v
    return p


def test_normalize_and_validate_ok():
    w = om.normalize_archive(payload())
    assert list(w.columns) == om.COLUMNS
    om.validate(w, date(2015, 1, 1), date(2016, 12, 31))
    assert om.complete_years(w) == [2015, 2016]


def test_request_params_pin_timezone_and_variables():
    p = om.request_params(30.787, 72.318, date(2014, 1, 1), date(2025, 12, 31), "era5_seamless")
    assert p["timezone"] == "Asia/Karachi" and p["models"] == "era5_seamless"
    assert p["daily"].split(",") == list(om.VARIABLES)


def test_missing_day_rejected():
    p = payload()
    for k in p["daily"]:
        del p["daily"][k][100]
    w = om.normalize_archive(p)
    with pytest.raises(om.WeatherValidationError, match="missing"):
        om.validate(w, date(2015, 1, 1), date(2016, 12, 31))


def test_duplicate_day_rejected():
    p = payload()
    p["daily"]["time"][5] = p["daily"]["time"][4]
    with pytest.raises(om.WeatherValidationError, match="duplicate"):
        om.validate(om.normalize_archive(p), date(2015, 1, 1), date(2016, 12, 31))


@pytest.mark.parametrize(
    ("var", "value", "msg"),
    [
        ("precipitation_sum", None, "missing values"),
        ("temperature_2m_min", 30.0, "MinTemp > MaxTemp"),
        ("precipitation_sum", -1.0, "negative"),
        ("et0_fao_evapotranspiration", math.inf, "nonfinite"),
        ("temperature_2m_max", 80.0, "physical range"),
    ],
)
def test_bad_values_rejected_not_coerced(var, value, msg):
    vals = payload()["daily"][var]
    vals[10] = value
    w = om.normalize_archive(payload(**{var: vals}))
    with pytest.raises(om.WeatherValidationError, match=msg):
        om.validate(w, date(2015, 1, 1), date(2016, 12, 31))


def test_wrong_timezone_or_units_rejected():
    p = payload()
    p["timezone"] = "GMT"
    with pytest.raises(om.WeatherValidationError, match="timezone"):
        om.normalize_archive(p)
    p = payload()
    p["daily_units"]["precipitation_sum"] = "inch"
    with pytest.raises(om.WeatherValidationError, match="unit"):
        om.normalize_archive(p)
    p = payload()
    del p["daily"]["et0_fao_evapotranspiration"]
    with pytest.raises(om.WeatherValidationError, match="missing variable"):
        om.normalize_archive(p)


def test_partial_year_not_counted_and_series_id():
    w = om.normalize_archive(payload(days=400))
    assert om.complete_years(w) == [2015]
    pt = om.returned_point(payload())
    sid = om.series_id_for(pt, date(2014, 1, 1), date(2025, 12, 31))
    assert sid == "openmeteo-archive-30.8000N-72.3000E-20140101-20251231"


def test_parquet_roundtrip(tmp_path):
    w = om.normalize_archive(payload())
    p = tmp_path / "w.parquet"
    p.write_bytes(om.to_parquet_bytes(w))
    back = pd.read_parquet(p)
    assert list(back.columns) == om.COLUMNS and len(back) == len(w)
