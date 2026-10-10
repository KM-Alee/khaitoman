"""Weather scenarios, supply profiles and uncertainty sets (PRD §5.4, §7.3; T3.5, T7.2).

Weather analog rule (documented, deterministic):

1. Candidate pool: every historical season (same crop calendar) whose whole
   simulation window lies in the archive and ends before the season's decision
   date; at least ``MIN_POOL`` seasons are required.
2. Statistic: crop-season water balance ``P - ET0`` (mm) summed from planting to
   planting + ``STAT_DAYS[crop]`` (the typical crop duration).
3. Seasons are ranked by the statistic; with ``n`` seasons and ``k = n // 3``:
   dry = median of the lowest third (rank ``(k - 1) // 2``), typical = median of
   all (rank ``(n - 1) // 2``), wet = median of the top third
   (rank ``n - k + (k - 1) // 2``). Labels describe those selected years, not
   probability forecasts.
4. Each selected season keeps its original daily sequence, mapped to the
   scenario calendar by planting-relative offset (``weather.LEAP_RULE``).
5. Heat/timing inspection: hot days (Tmax >= threshold) in the late window,
   monthly rainfall shares and the max 10-day rain total are stored so that
   equal totals with different distributions remain visible.

``wheat-rabi-2024-25`` is a historical replay: its typical member is the
``actual`` archived 2024-25 weather on original dates; dry/typical/wet analogs
from seasons before its decision date are published for stress tests.

Supply: base ``nominal-roster-v1`` (pilot roster at declared rates), plus
``shortage-22pct-v1`` (absolute multiplier 0.78) and ``interruption-14d-v1``
(whole-source closure for 14 days at a critical stage). The release
uncertainty set is the 3 weather x 3 supply grid (9 states).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aabflow.domain.calendar import PKT, to_utc
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import (
    Crop,
    Season,
    SupplyProfile,
    SupplyTransformation,
    UncertaintySet,
    UncertaintyState,
    WeatherScenario,
)
from aabflow.science import crop_profiles
from aabflow.science.paths import atomic_write_text, libraries_dir, pilots_dir
from aabflow.science.weather import (
    LEAP_RULE,
    acquire_point_series,
    grid_cell_key,
    map_analog,
    slice_window,
    store_weather,
    validate_weather,
    weather_sha256,
)

DISCOVERY_POINT = (30.8, 72.5)  # inside the published Mungi search extent (discovery only)
DISCOVERY_SERIES_ID = "discovery-lower-chenab-era5"
ARCHIVE_START = date(2000, 1, 1)
ARCHIVE_END = date(2026, 9, 30)
MIN_POOL = 10
STAT_DAYS = {Crop.wheat: 145, Crop.cotton: 174}
HEAT_THRESHOLD_C = {Crop.wheat: 35.0, Crop.cotton: 45.0}
HEAT_WINDOW = {Crop.wheat: (100, 145), Crop.cotton: (60, 120)}  # DAP window for heat inspection
SELECTION_VERSION = "analog-selection-v1"

NOMINAL = "nominal-roster-v1"
SHORTAGE = "shortage-22pct-v1"
INTERRUPTION = "interruption-14d-v1"
SUPPLY_IDS = (NOMINAL, SHORTAGE, INTERRUPTION)
INTERRUPTION_DAP = {Crop.wheat: 90, Crop.cotton: 75}  # closure start (days after planting)
INTERRUPTION_DAYS = 14


class ScenarioError(ValueError):
    pass


# --------------------------------------------------------------------------- weather source


@dataclass(frozen=True)
class WeatherSource:
    series_id: str
    frame: pd.DataFrame
    point_requested: tuple[float, float]
    point_returned: tuple[float, float]
    grid_cell: str
    origin: str  # "pilot-package:<pilot>/<version>" or "science-discovery-fetch"
    meta: dict[str, Any]


def _pilot_weather(pilot_id: str) -> WeatherSource | None:
    """Pilot package weather (data stream) if published and complete."""
    root = pilots_dir() / pilot_id
    if not root.exists():
        return None
    for vdir in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        idx = vdir / "weather" / "index.json"
        if not idx.exists():
            continue
        rows = json.loads(idx.read_text())
        rows = rows if isinstance(rows, list) else rows.get("series", [])
        for row in rows:
            norm = vdir / "weather" / Path(row["normalized_ref"]).name
            if not norm.exists():
                norm = vdir / row["normalized_ref"]
            if not norm.exists():
                continue
            df = pd.read_parquet(norm)
            df["Date"] = pd.to_datetime(df["Date"]).astype("datetime64[ns]")
            df = df[["Date", "MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]].sort_values("Date")
            start, end = df["Date"].min().date(), df["Date"].max().date()
            validate_weather(df.reset_index(drop=True), start, end)
            ret = tuple(row.get("point_returned") or row.get("point_requested"))
            return WeatherSource(
                row["weather_series_id"],
                df.reset_index(drop=True),
                tuple(row.get("point_requested") or ret),
                ret,
                grid_cell_key(*ret),
                f"pilot-package:{pilot_id}/{vdir.name}",
                row,
            )
    return None


def weather_source(pilot_id: str | None) -> WeatherSource:
    """Pilot package weather when available; otherwise the discovery-point archive fetch."""
    if pilot_id:
        src = _pilot_weather(pilot_id)
        if src is not None:
            return src
    s = acquire_point_series(DISCOVERY_SERIES_ID, *DISCOVERY_POINT, ARCHIVE_START, ARCHIVE_END)
    ret = tuple(s.meta["point_returned"])
    return WeatherSource(
        DISCOVERY_SERIES_ID,
        s.frame,
        tuple(s.meta["point_requested"]),
        ret,
        grid_cell_key(*ret),
        "science-discovery-fetch",
        s.meta,
    )


# --------------------------------------------------------------------------- analog selection


def season_statistics(df: pd.DataFrame, crop: Crop, planting: date) -> dict[str, float]:
    n = STAT_DAYS[crop]
    w = slice_window(df, planting, planting + timedelta(days=n - 1))
    p, et0 = float(w["Precipitation"].sum()), float(w["ReferenceET"].sum())
    h0, h1 = HEAT_WINDOW[crop]
    late = w.iloc[h0:h1]
    stats = {
        "precip_mm": round(p, 3),
        "et0_mm": round(et0, 3),
        "p_minus_et0_mm": round(p - et0, 3),
        "hot_days_late": float((late["MaxTemp"] >= HEAT_THRESHOLD_C[crop]).sum()),
        "mean_tmax_late_c": round(float(late["MaxTemp"].mean()), 3),
        "max_10day_precip_mm": round(float(w["Precipitation"].rolling(10).sum().max()), 3),
    }
    months = w.groupby(w["Date"].dt.month)["Precipitation"].sum()
    for m, v in months.items():
        stats[f"precip_share_m{int(m):02d}"] = round(float(v / p), 4) if p > 0 else 0.0
    return stats


def candidate_plantings(season: Season, src: WeatherSource) -> list[date]:
    cp = crop_profiles.profile(season.crop_profile_id)
    first, last = src.frame["Date"].min().date(), src.frame["Date"].max().date()
    decision = season.decision_at.astimezone(PKT).date() if season.decision_at else season.start
    out = []
    for y in range(first.year - 1, last.year + 1):
        planting = date(y, cp.planting_date.month, cp.planting_date.day)
        start, end = crop_profiles.season_window(cp, planting)
        if start >= first and end <= last and end < decision and planting != season.planting_date:
            out.append(planting)
    return out


def select_analogs(season: Season, src: WeatherSource) -> tuple[dict[str, date], list[dict[str, Any]]]:
    plantings = candidate_plantings(season, src)
    if len(plantings) < MIN_POOL:
        raise ScenarioError(f"{season.season_id}: only {len(plantings)} complete historical seasons")
    rows = []
    for p in plantings:
        st = season_statistics(src.frame, season.crop, p)
        rows.append({"planting": p, "label": _label(season.crop, p), **st})
    ranked = sorted(rows, key=lambda r: (r["p_minus_et0_mm"], r["planting"]))
    n, k = len(ranked), len(ranked) // 3
    pick = {
        "dry": ranked[(k - 1) // 2]["planting"],
        "typical": ranked[(n - 1) // 2]["planting"],
        "wet": ranked[n - k + (k - 1) // 2]["planting"],
    }
    for i, r in enumerate(ranked):
        r["rank"] = i
        r["planting"] = r["planting"].isoformat()
    return pick, ranked


def _label(crop: Crop, planting: date) -> str:
    return f"{planting.year}-{str(planting.year + 1)[-2:]}" if crop is Crop.wheat else str(planting.year)


def build_weather_scenarios(season: Season, src: WeatherSource) -> tuple[list[WeatherScenario], dict]:
    """Map selected analogs onto the season and store transformed weather + date tables."""
    cp = crop_profiles.profile(season.crop_profile_id)
    pick, ranked = select_analogs(season, src)
    n_days = (season.sim_end - season.sim_start).days + 1
    out: list[WeatherScenario] = []
    tables_dir = libraries_dir() / "weather" / "mappings"
    tables_dir.mkdir(parents=True, exist_ok=True)
    basis = (
        f"{SELECTION_VERSION}: rank of crop-season P-ET0 (planting..+{STAT_DAYS[season.crop]} d) over "
        f"{len(ranked)} historical seasons {ranked[0]['label'] if ranked else ''}.. preceding the decision "
        "date; dry/wet = medians of lowest/highest third, typical = overall median"
    )
    actual_typical = season.weather_basis == "actual"
    for wid, planting in pick.items():
        a_start, _ = crop_profiles.season_window(cp, planting)
        m = map_analog(src.frame, a_start, season.sim_start, n_days)
        sha, _ = store_weather(m.weather)
        tref = f"weather/mappings/{season.season_id}--{wid}.csv"
        m.table.to_csv(libraries_dir() / tref, index=False)
        stats = next(r for r in ranked if r["planting"] == planting.isoformat())
        out.append(
            WeatherScenario(
                weather_scenario_id=wid,
                season_id=season.season_id,
                label=f"{wid} analog ({_label(season.crop, planting)})",
                analog_season_start=a_start,
                weather_series_id=src.series_id,
                date_mapping_ref=tref,
                transformed_sha256=sha,
                is_typical=(wid == "typical" and not actual_typical),
                selection_basis=basis,
                analog_season_label=_label(season.crop, planting),
                original_start=a_start,
                original_end=a_start + timedelta(days=n_days - 1),
                scenario_start=season.sim_start,
                scenario_end=season.sim_end,
                offset_days=m.offset_days,
                leap_rule=m.rule,
                leap_note=m.leap_drift_note,
                source_sha256=m.source_sha256,
                grid_cell=src.grid_cell,
                statistics={k: float(v) for k, v in stats.items() if isinstance(v, (int, float))},
                kind="analog",
            )
        )
    if actual_typical:
        w = slice_window(src.frame, season.sim_start, season.sim_end)
        sha, _ = store_weather(w)
        st = season_statistics(src.frame, season.crop, season.planting_date)
        out.append(
            WeatherScenario(
                weather_scenario_id="actual",
                season_id=season.season_id,
                label=f"actual archived weather {_label(season.crop, season.planting_date)}",
                analog_season_start=season.sim_start,
                weather_series_id=src.series_id,
                date_mapping_ref=None,
                transformed_sha256=sha,
                is_typical=True,
                selection_basis="historical replay: actual archived gridded weather on original dates",
                analog_season_label=_label(season.crop, season.planting_date),
                original_start=season.sim_start,
                original_end=season.sim_end,
                scenario_start=season.sim_start,
                scenario_end=season.sim_end,
                offset_days=0,
                leap_rule="identity",
                source_sha256=sha,
                grid_cell=src.grid_cell,
                statistics={k: float(v) for k, v in st.items()},
                kind="actual",
            )
        )
    inspection = {
        "season_id": season.season_id,
        "rule": SELECTION_VERSION,
        "statistic": "p_minus_et0_mm",
        "pool": ranked,
        "selected": {k: v.isoformat() for k, v in pick.items()},
        "weather_source": src.origin,
        "series_id": src.series_id,
        "grid_cell": src.grid_cell,
        "leap_rule": LEAP_RULE,
    }
    return out, inspection


def historical_season_weather(season: Season, src: WeatherSource) -> list[tuple[str, date, str]]:
    """All complete historical seasons on their original dates: (label, planting, sha)."""
    cp = crop_profiles.profile(season.crop_profile_id)
    out = []
    for planting in candidate_plantings(season, src):
        start, end = crop_profiles.season_window(cp, planting)
        sha, _ = store_weather(slice_window(src.frame, start, end))
        out.append((_label(season.crop, planting), planting, sha))
    return out


# --------------------------------------------------------------------------- supply


def local_midnight(d: date) -> datetime:
    return to_utc(datetime(d.year, d.month, d.day, tzinfo=PKT))


def supply_profiles(season: Season, base_profile_hash: str) -> list[SupplyProfile]:
    from aabflow.water.roster import profile_hash

    c0 = season.planting_date + timedelta(days=INTERRUPTION_DAP[season.crop])
    specs = [
        (NOMINAL, "Nominal roster (declared rates, no curtailment)", []),
        (
            SHORTAGE,
            "22% uniform supply shortage (absolute multiplier 0.78)",
            [SupplyTransformation(transformation_id="shortage-22pct", kind="absolute_multiplier", multiplier=0.78)],
        ),
        (
            INTERRUPTION,
            f"14-day whole-source closure from {c0.isoformat()} (DAP {INTERRUPTION_DAP[season.crop]})",
            [
                SupplyTransformation(
                    transformation_id="interruption-14d",
                    kind="closure",
                    start=local_midnight(c0),
                    end=local_midnight(c0 + timedelta(days=INTERRUPTION_DAYS)),
                    edge_ids=[],
                )
            ],
        ),
    ]
    return [
        SupplyProfile(
            supply_profile_id=sid,
            base_profile_hash=base_profile_hash,
            label=label,
            transformations=tr,
            resolved_hash=profile_hash(sid, base_profile_hash, tr),
        )
        for sid, label, tr in specs
    ]


def generic_base_hash(season: Season) -> str:
    return content_hash({"base": NOMINAL, "season_id": season.season_id, "rule": "pilot roster at declared rates"})


def state_id(weather_id: str, supply_id: str) -> str:
    return f"{weather_id}__{supply_id}"


def uncertainty_set(pilot_id: str, season: Season, profiles: list[SupplyProfile]) -> UncertaintySet:
    states = [
        UncertaintyState(
            state_id=state_id(w, p.supply_profile_id),
            weather_scenario_id=w,
            supply_profile_id=p.supply_profile_id,
            resolved_supply_profile_hash=p.resolved_hash,
        )
        for w in ("dry", "typical", "wet")
        for p in profiles
    ]
    return UncertaintySet(
        uncertainty_set_id=f"{pilot_id}:{season.season_id}:release-9",
        pilot_id=pilot_id,
        season_id=season.season_id,
        states=states,
    )


# --------------------------------------------------------------------------- publication


def published_pilots() -> list[tuple[str, str]]:
    idx = pilots_dir() / "index.json"
    if not idx.exists():
        return []
    rows = json.loads(idx.read_text())
    rows = rows.get("pilots", rows) if isinstance(rows, dict) else rows
    return [(r["pilot_id"], r["pilot_version"]) for r in rows]


def scenario_key(pilot_id: str | None) -> str:
    """Weather scenarios are keyed by weather grid cell; pilots sharing a cell share them."""
    return weather_source(pilot_id).grid_cell


def publish(pilot_ids: list[str] | None = None) -> dict[str, Any]:
    """Write seasons, crop profiles, weather scenarios and supply/uncertainty libraries."""
    crop_profiles.publish()
    pilots = pilot_ids if pilot_ids is not None else [p for p, _ in published_pilots()]
    sources: dict[str, WeatherSource] = {}
    for pid in pilots or [None]:
        src = weather_source(pid)
        sources.setdefault(src.grid_cell, src)
    by_cell: dict[str, Any] = {}
    inspections = []
    for cell, src in sources.items():
        scen = []
        for s in crop_profiles.SEASONS.values():
            ws, insp = build_weather_scenarios(s, src)
            scen.extend(w.model_dump(mode="json") for w in ws)
            inspections.append(insp)
        by_cell[cell] = {"weather_series_id": src.series_id, "origin": src.origin, "scenarios": scen}
    pilot_cells = {pid: weather_source(pid).grid_cell for pid in pilots}
    default_cell = next(iter(sources))
    doc = {
        "version": SELECTION_VERSION,
        "label": "historical gridded weather analogs (not probability forecasts)",
        "default_grid_cell": default_cell,
        "pilot_grid_cells": pilot_cells,
        "shared_grid_cell": len(set(pilot_cells.values())) == 1 and len(pilot_cells) > 1,
        "grid_cells": by_cell,
        # Flat list for the default cell (API convenience).
        "scenarios": by_cell[default_cell]["scenarios"],
    }
    atomic_write_text(libraries_dir() / "weather_scenarios.json", json.dumps(doc, indent=2, default=str))
    atomic_write_text(
        libraries_dir() / "weather" / "analog_inspection.json", json.dumps(inspections, indent=2, default=str)
    )
    publish_supply(pilots)
    return doc


def publish_supply(pilots: list[str]) -> dict[str, Any]:
    from aabflow.water.context import load_pilot

    seasons_doc: dict[str, Any] = {}
    usets: list[dict] = []
    for s in crop_profiles.SEASONS.values():
        seasons_doc[s.season_id] = {
            "generic": [p.model_dump(mode="json") for p in supply_profiles(s, generic_base_hash(s))],
            "by_pilot": {},
        }
        for pid in pilots:
            try:
                pdata = load_pilot(pid)
            except Exception:  # noqa: BLE001 - unpublished pilot: generic profiles only
                continue
            base = content_hash({"base": NOMINAL, "season_id": s.season_id, "roster": pdata.roster_hash(s.season_id),
                                 "pilot_version": pdata.pilot_version})
            profs = supply_profiles(s, base)
            seasons_doc[s.season_id]["by_pilot"][pid] = [p.model_dump(mode="json") for p in profs]
            usets.append(uncertainty_set(pid, s, profs).model_dump(mode="json"))
    doc = {
        "version": "supply-v1",
        "supply_profile_ids": list(SUPPLY_IDS),
        "seasons": seasons_doc,
        "uncertainty_sets": usets,
        "notes": [
            "A scalar request reduction multiplies the named base schedule once; pre-reduced profiles "
            "reject an additional reduction (aabflow.water.roster.resolve_supply).",
            "Worst case means worst within the nine tested states, not a probability.",
        ],
    }
    atomic_write_text(libraries_dir() / "supply.json", json.dumps(doc, indent=2, default=str))
    return doc


def load_weather_scenarios(season_id: str, pilot_id: str | None = None) -> list[WeatherScenario]:
    p = libraries_dir() / "weather_scenarios.json"
    if not p.exists():
        raise ScenarioError("weather_scenarios.json not published (run scripts/science_publish.py)")
    doc = json.loads(p.read_text())
    cell = doc["pilot_grid_cells"].get(pilot_id) if pilot_id else None
    cell = cell or doc["default_grid_cell"]
    rows = doc["grid_cells"][cell]["scenarios"]
    return [WeatherScenario.model_validate(r) for r in rows if r["season_id"] == season_id]


def load_supply_profiles(season_id: str, pilot_id: str | None = None) -> list[SupplyProfile]:
    p = libraries_dir() / "supply.json"
    if not p.exists():
        raise ScenarioError("supply.json not published")
    doc = json.loads(p.read_text())["seasons"][season_id]
    rows = doc["by_pilot"].get(pilot_id) if pilot_id else None
    return [SupplyProfile.model_validate(r) for r in (rows or doc["generic"])]


def weather_daily(sha: str) -> dict[date, tuple[float, float]]:
    from aabflow.science.weather import load_weather

    df = load_weather(sha)
    return {
        d.date(): (float(p), float(e))
        for d, p, e in zip(pd.DatetimeIndex(df["Date"]), df["Precipitation"], df["ReferenceET"], strict=True)
    }


def _np_safe(x: Any) -> Any:
    return x.item() if isinstance(x, np.generic) else x


__all__ = [
    "INTERRUPTION",
    "NOMINAL",
    "SHORTAGE",
    "SUPPLY_IDS",
    "build_weather_scenarios",
    "load_supply_profiles",
    "load_weather_scenarios",
    "publish",
    "state_id",
    "weather_sha256",
    "weather_source",
]
