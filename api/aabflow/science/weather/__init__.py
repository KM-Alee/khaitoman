"""Historical gridded weather: acquisition, normalization, validation, analog mapping (T2.5).

Weather is "historical gridded weather" (reanalysis), never a station in a field.
Validation rejects missing/duplicate dates, nonfinite values and nonsensical
physical ranges with a useful error; nothing is silently interpolated.

Analog mapping for future seasons aligns an analog season to the scenario by
planting-relative day offset and records an ``original_date -> scenario_date``
table. Leap-day rule (``LEAP_RULE``): *offset preserving* — every original day
maps to exactly one scenario day at the same days-after-planting offset; no row
is dropped or interpolated, so daily continuity and the thermal sequence are
kept. When exactly one of the two calendars contains 29 February the month-day
label drifts by one day after 28 February; that drift is recorded per mapping.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aabflow.domain.hashes import content_hash, file_sha256, sha256_hex
from aabflow.science.paths import atomic_write_bytes, atomic_write_text, weather_store_dir

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVE_MODEL = "era5"  # pinned documented archive model (0.25 deg ERA5 reanalysis)
TIMEZONE = "Asia/Karachi"
DAILY_VARIABLES = {
    "temperature_2m_min": ("MinTemp", "degC"),
    "temperature_2m_max": ("MaxTemp", "degC"),
    "precipitation_sum": ("Precipitation", "mm/day"),
    "et0_fao_evapotranspiration": ("ReferenceET", "mm/day"),
}
WEATHER_COLUMNS = ["Date", "MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]
VALUE_COLUMNS = WEATHER_COLUMNS[1:]
# Physically plausible daily ranges for Punjab plains; outside => reject (not clip).
PHYSICAL_RANGES: dict[str, tuple[float, float]] = {
    "MinTemp": (-15.0, 45.0),
    "MaxTemp": (-5.0, 55.0),
    "Precipitation": (0.0, 400.0),
    "ReferenceET": (0.0, 20.0),
}
LEAP_RULE = "offset_preserving_v1"
NORMALIZATION_VERSION = "weather-normalize-v1"


class WeatherValidationError(ValueError):
    """Weather input is incomplete, duplicated, nonfinite or physically implausible."""


# --------------------------------------------------------------------------- acquisition


def request_archive(
    lat: float,
    lon: float,
    start: date,
    end: date,
    *,
    model: str | None = ARCHIVE_MODEL,
    retries: int = 5,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Fetch the Open-Meteo archive with bounded exponential backoff.

    The returned payload carries a ``_request`` block (url, params, retrieved_at)
    so the raw file is self-describing.
    """
    import httpx

    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": TIMEZONE,
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    }
    if model:
        params["models"] = model
    delay = 2.0
    last: Exception | None = None
    for _ in range(retries):
        try:
            r = httpx.get(ARCHIVE_URL, params=params, timeout=timeout_s)
            if r.status_code == 429 or r.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            r.raise_for_status()
            payload = r.json()
            payload["_request"] = {
                "url": ARCHIVE_URL,
                "params": params,
                "retrieved_at": datetime.now(UTC).isoformat(),
            }
            return payload
        except (httpx.HTTPError, ValueError) as exc:  # network, 5xx, 429, bad JSON
            last = exc
            time.sleep(delay)
            delay *= 2
    raise WeatherValidationError(f"Open-Meteo archive request failed after {retries} tries: {last}")


def normalize_archive(payload: dict[str, Any]) -> pd.DataFrame:
    """Map archive variables to AquaCrop columns. Missing values stay NaN (validated later)."""
    if "daily" not in payload:
        raise WeatherValidationError(f"archive payload has no 'daily' block: {payload.get('reason')}")
    daily = payload["daily"]
    units = payload.get("daily_units", {})
    expected_units = {"temperature_2m_min": "°C", "temperature_2m_max": "°C"}
    for var, unit in expected_units.items():
        if var in units and units[var] != unit:
            raise WeatherValidationError(f"{var} unit {units[var]!r}, expected {unit!r}")
    for var in ("precipitation_sum", "et0_fao_evapotranspiration"):
        if var in units and units[var] != "mm":
            raise WeatherValidationError(f"{var} unit {units[var]!r}, expected 'mm'")
    missing = [v for v in ["time", *DAILY_VARIABLES] if v not in daily]
    if missing:
        raise WeatherValidationError(f"archive payload lacks variables {missing}")
    out = pd.DataFrame({"Date": pd.to_datetime(daily["time"]).normalize()})
    for var, (col, _unit) in DAILY_VARIABLES.items():
        out[col] = pd.to_numeric(pd.Series(daily[var], dtype="object"), errors="coerce").astype(
            "float64"
        )
    return out[WEATHER_COLUMNS]


def validate_weather(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """T2.5 assertions as explicit errors. Returns the frame unchanged when valid."""
    if list(df.columns) != WEATHER_COLUMNS:
        raise WeatherValidationError(f"columns {list(df.columns)} != {WEATHER_COLUMNS}")
    dates = pd.DatetimeIndex(df["Date"])
    if not dates.is_unique:
        dup = dates[dates.duplicated()].strftime("%Y-%m-%d").tolist()[:5]
        raise WeatherValidationError(f"duplicate dates: {dup}")
    expected = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    if not dates.equals(expected):
        missing = expected.difference(dates).strftime("%Y-%m-%d").tolist()
        extra = dates.difference(expected).strftime("%Y-%m-%d").tolist()
        raise WeatherValidationError(
            f"dates are not the complete daily range {start}..{end}: "
            f"missing={missing[:5]}{'...' if len(missing) > 5 else ''} extra={extra[:5]}"
        )
    values = df[VALUE_COLUMNS].to_numpy(dtype="float64")
    if np.isnan(values).any():
        bad = df.loc[df[VALUE_COLUMNS].isna().any(axis=1), "Date"].dt.strftime("%Y-%m-%d")
        raise WeatherValidationError(f"missing values on {bad.tolist()[:5]} (never interpolated)")
    if not np.isfinite(values).all():
        raise WeatherValidationError("nonfinite (inf) weather values")
    if not (df["MinTemp"] <= df["MaxTemp"]).all():
        bad = df.loc[df["MinTemp"] > df["MaxTemp"], "Date"].dt.strftime("%Y-%m-%d")
        raise WeatherValidationError(f"MinTemp > MaxTemp on {bad.tolist()[:5]}")
    if not (df[["Precipitation", "ReferenceET"]] >= 0).all().all():
        raise WeatherValidationError("negative precipitation or reference ET")
    for col, (lo, hi) in PHYSICAL_RANGES.items():
        s = df[col]
        if ((s < lo) | (s > hi)).any():
            bad = df.loc[(s < lo) | (s > hi), ["Date", col]].head(3).to_dict("records")
            raise WeatherValidationError(f"{col} outside physical range [{lo}, {hi}]: {bad}")
    return df


# --------------------------------------------------------------------------- hashing / store


def weather_sha256(df: pd.DataFrame) -> str:
    """Content hash of the daily values (dates + 4 variables), independent of file encoding."""
    rows = [
        [d.strftime("%Y-%m-%d"), *(float(v) for v in vals)]
        for d, vals in zip(
            pd.DatetimeIndex(df["Date"]), df[VALUE_COLUMNS].to_numpy(dtype="float64"), strict=True
        )
    ]
    return content_hash({"columns": WEATHER_COLUMNS, "rows": rows})


def store_weather(df: pd.DataFrame) -> tuple[str, Path]:
    """Persist a validated frame at ``weather/<sha>.parquet`` (idempotent)."""
    sha = weather_sha256(df)
    path = weather_store_dir() / f"{sha}.parquet"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{id(df)}.tmp")
        df.reset_index(drop=True).to_parquet(tmp, index=False)
        tmp.replace(path)
    return sha, path


def load_weather(sha: str) -> pd.DataFrame:
    path = weather_store_dir() / f"{sha}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"weather {sha} not in store {path.parent}")
    df = pd.read_parquet(path)
    df["Date"] = pd.to_datetime(df["Date"]).astype("datetime64[ns]")
    if weather_sha256(df) != sha:
        raise WeatherValidationError(f"weather store file {path} does not match its hash")
    return df[WEATHER_COLUMNS]


def slice_window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    m = (df["Date"] >= pd.Timestamp(start)) & (df["Date"] <= pd.Timestamp(end))
    out = df.loc[m, WEATHER_COLUMNS].reset_index(drop=True)
    return validate_weather(out, start, end)


# --------------------------------------------------------------------------- analog mapping


@dataclass(frozen=True)
class AnalogMapping:
    weather: pd.DataFrame  # scenario-dated frame
    table: pd.DataFrame  # original_date, scenario_date, days_after_sim_start
    rule: str
    offset_days: int
    leap_drift_note: str | None
    source_sha256: str
    transformed_sha256: str


def map_analog(
    source: pd.DataFrame,
    analog_start: date,
    scenario_start: date,
    n_days: int,
) -> AnalogMapping:
    """Map ``n_days`` from ``analog_start`` onto ``scenario_start`` (offset preserving).

    ``analog_start`` and ``scenario_start`` are the same planting-relative day
    (sim start = planting - lead days in both calendars).
    """
    if n_days <= 0:
        raise WeatherValidationError("n_days must be positive")
    analog_end = analog_start + timedelta(days=n_days - 1)
    orig = slice_window(source, analog_start, analog_end)
    offset = (scenario_start - analog_start).days
    mapped = orig.copy()
    mapped["Date"] = mapped["Date"] + pd.Timedelta(days=offset)
    scenario_end = scenario_start + timedelta(days=n_days - 1)
    validate_weather(mapped, scenario_start, scenario_end)
    table = pd.DataFrame(
        {
            "original_date": orig["Date"].dt.strftime("%Y-%m-%d"),
            "scenario_date": mapped["Date"].dt.strftime("%Y-%m-%d"),
            "days_after_sim_start": np.arange(n_days, dtype="int64"),
        }
    )

    def has_feb29(a: date, b: date) -> bool:
        return any(
            (d.month, d.day) == (2, 29) for d in pd.date_range(a, b, freq="D").to_pydatetime()
        )

    src_leap, dst_leap = has_feb29(analog_start, analog_end), has_feb29(scenario_start, scenario_end)
    note = None
    if src_leap != dst_leap:
        note = (
            "exactly one calendar contains 29 Feb; month-day labels drift by one day after 28 Feb "
            f"({'source' if src_leap else 'scenario'} is leap); no rows dropped or interpolated"
        )
    return AnalogMapping(
        weather=mapped,
        table=table,
        rule=LEAP_RULE,
        offset_days=offset,
        leap_drift_note=note,
        source_sha256=weather_sha256(orig),
        transformed_sha256=weather_sha256(mapped),
    )


# --------------------------------------------------------------------------- series acquisition


@dataclass(frozen=True)
class AcquiredSeries:
    series_id: str
    directory: Path
    frame: pd.DataFrame
    meta: dict[str, Any]


def acquire_point_series(
    series_id: str, lat: float, lon: float, start: date, end: date, *, refresh: bool = False
) -> AcquiredSeries:
    """Fetch (once), save immutable raw JSON + normalized parquet, validate, record metadata."""
    d = weather_store_dir() / "series" / series_id
    raw_path, norm_path, meta_path = d / "raw.json", d / "normalized.parquet", d / "series.json"
    if meta_path.exists() and not refresh:
        meta = json.loads(meta_path.read_text())
        df = pd.read_parquet(norm_path)
        df["Date"] = pd.to_datetime(df["Date"]).astype("datetime64[ns]")
        return AcquiredSeries(series_id, d, df[WEATHER_COLUMNS], meta)
    payload = request_archive(lat, lon, start, end)
    raw_bytes = json.dumps(payload, sort_keys=True).encode()
    atomic_write_bytes(raw_path, raw_bytes)
    df = normalize_archive(payload)
    validate_weather(df, start, end)
    norm_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(norm_path, index=False)
    meta = {
        "weather_series_id": series_id,
        "point_requested": [lat, lon],
        "point_returned": [payload.get("latitude"), payload.get("longitude")],
        "elevation_m": payload.get("elevation"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source": "open-meteo-archive",
        "source_model": ARCHIVE_MODEL,
        "timezone": payload.get("timezone"),
        "daily_units": payload.get("daily_units"),
        "raw_ref": str(raw_path.relative_to(weather_store_dir())),
        "normalized_ref": str(norm_path.relative_to(weather_store_dir())),
        "source_sha256": sha256_hex(raw_bytes),
        "normalized_sha256": file_sha256(norm_path),
        "content_sha256": weather_sha256(df),
        "normalization_version": NORMALIZATION_VERSION,
        "retrieved_at": payload["_request"]["retrieved_at"],
        "label": "historical gridded weather (ERA5 reanalysis via Open-Meteo), not a field station",
    }
    atomic_write_text(meta_path, json.dumps(meta, indent=2))
    return AcquiredSeries(series_id, d, df, meta)


def grid_cell_key(lat: float, lon: float) -> str:
    """Key identifying a returned archive grid point (pilots in one cell share weather)."""
    return f"{round(lat, 4):.4f},{round(lon, 4):.4f}"


def is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)
