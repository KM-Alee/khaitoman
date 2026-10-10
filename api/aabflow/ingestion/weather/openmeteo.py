"""Open-Meteo historical archive weather (T2.5).

Daily ``temperature_2m_min/max``, ``precipitation_sum`` and
``et0_fao_evapotranspiration`` for the pilot centroid, ``timezone=Asia/Karachi``,
metric units. Raw JSON is stored immutably; the normalized Parquet has columns
``Date, MinTemp, MaxTemp, Precipitation, ReferenceET`` with a complete daily index.
Missing or nonphysical values raise; nothing is interpolated.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..common import FetchResult, IngestionError, http_request

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
LICENSE_ID = "CC-BY-4.0"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0); ERA5/ERA5-Land reanalysis (Copernicus)"
TIMEZONE = "Asia/Karachi"

VARIABLES = {
    "temperature_2m_min": ("MinTemp", "°C"),
    "temperature_2m_max": ("MaxTemp", "°C"),
    "precipitation_sum": ("Precipitation", "mm"),
    "et0_fao_evapotranspiration": ("ReferenceET", "mm"),
}
EXPECTED_UNITS = {
    "temperature_2m_min": "°C",
    "temperature_2m_max": "°C",
    "precipitation_sum": "mm",
    "et0_fao_evapotranspiration": "mm",
}
COLUMNS = ["Date", "MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]

# Physical plausibility bounds for the Punjab plains (reject, never coerce).
BOUNDS = {
    "MinTemp": (-15.0, 45.0),
    "MaxTemp": (-10.0, 55.0),
    "Precipitation": (0.0, 500.0),
    "ReferenceET": (0.0, 20.0),
}


class WeatherValidationError(IngestionError):
    pass


def request_params(
    lat: float, lon: float, start: date, end: date, model: str | None = None
) -> dict:
    p = {
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(VARIABLES),
        "timezone": TIMEZONE,
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "timeformat": "iso8601",
    }
    if model:
        p["models"] = model
    return p


def request_archive(
    lat: float, lon: float, start: date, end: date, model: str | None = None
) -> FetchResult:
    return http_request(
        "GET", ARCHIVE_URL, params=request_params(lat, lon, start, end, model), timeout=180
    )


def normalize_archive(payload: dict) -> pd.DataFrame:
    if payload.get("error"):
        raise WeatherValidationError(f"Open-Meteo error: {payload.get('reason')}")
    daily = payload.get("daily")
    units = payload.get("daily_units") or {}
    if not daily or "time" not in daily:
        raise WeatherValidationError("payload has no daily block")
    if payload.get("timezone") != TIMEZONE:
        raise WeatherValidationError(f"timezone {payload.get('timezone')!r} != {TIMEZONE}")
    for var, unit in EXPECTED_UNITS.items():
        if var not in daily:
            raise WeatherValidationError(f"missing variable {var}")
        if units.get(var) != unit:
            raise WeatherValidationError(f"{var} unit {units.get(var)!r} != {unit!r}")
    n = len(daily["time"])
    data = {"Date": pd.to_datetime(daily["time"], format="%Y-%m-%d")}
    for var, (col, _) in VARIABLES.items():
        vals = daily[var]
        if len(vals) != n:
            raise WeatherValidationError(f"{var} length {len(vals)} != {n}")
        data[col] = pd.array([np.nan if v is None else float(v) for v in vals], dtype="float64")
    return pd.DataFrame(data)[COLUMNS]


def validate(w: pd.DataFrame, start: date, end: date) -> None:
    """The T2.5 asserts plus finite and physical-range checks, with useful errors."""
    expected = pd.date_range(start, end, freq="D")
    idx = pd.DatetimeIndex(w["Date"])
    if not w["Date"].is_unique:
        raise WeatherValidationError("duplicate dates")
    if not idx.equals(expected):
        missing = expected.difference(idx)
        extra = idx.difference(expected)
        raise WeatherValidationError(
            f"date index incomplete: {len(missing)} missing (first {list(missing[:3].date)}), "
            f"{len(extra)} unexpected"
        )
    vals = w[["MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]]
    if vals.isna().any().any():
        bad = vals.isna().any(axis=1)
        raise WeatherValidationError(
            f"{int(bad.sum())} days with missing values (first {w.loc[bad, 'Date'].iloc[0].date()})"
        )
    arr = vals.to_numpy(dtype="float64")
    if not np.isfinite(arr).all():
        raise WeatherValidationError("nonfinite weather values")
    if not (w["MinTemp"] <= w["MaxTemp"]).all():
        d = w.loc[w["MinTemp"] > w["MaxTemp"], "Date"].iloc[0].date()
        raise WeatherValidationError(f"MinTemp > MaxTemp on {d}")
    if not (w[["Precipitation", "ReferenceET"]] >= 0).all().all():
        raise WeatherValidationError("negative precipitation or reference ET")
    for col, (lo, hi) in BOUNDS.items():
        if (w[col] < lo).any() or (w[col] > hi).any():
            raise WeatherValidationError(f"{col} outside physical range [{lo}, {hi}]")


def complete_years(w: pd.DataFrame) -> list[int]:
    years = []
    for y, g in w.groupby(w["Date"].dt.year):
        n = 366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365
        if len(g) == n:
            years.append(int(y))
    return years


@dataclass
class ReturnedPoint:
    lat: float
    lon: float
    elevation_m: float | None


def returned_point(payload: dict) -> ReturnedPoint:
    lat, lon = payload.get("latitude"), payload.get("longitude")
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        raise WeatherValidationError("response lacks returned coordinates")
    return ReturnedPoint(float(lat), float(lon), payload.get("elevation"))


def series_id_for(point: ReturnedPoint, start: date, end: date) -> str:
    """Series id derived from the returned grid cell (shared when pilots share a cell)."""
    return f"openmeteo-archive-{point.lat:.4f}N-{point.lon:.4f}E-{start:%Y%m%d}-{end:%Y%m%d}"


def to_parquet_bytes(w: pd.DataFrame) -> bytes:
    import io

    buf = io.BytesIO()
    out = w.copy()
    out["Date"] = out["Date"].dt.date
    out.to_parquet(buf, index=False)
    return buf.getvalue()


def load_raw(content: bytes) -> dict:
    return json.loads(content)
