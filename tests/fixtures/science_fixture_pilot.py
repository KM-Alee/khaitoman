"""TEST FIXTURE (synthetic, labelled): a small pilot package for science/water tests.

This is NOT pilot evidence. Geometry, rights, capacities and costs are invented
for exercising the ledger and candidate generator. Fields: four parcels on one
watercourse with three reaches of distinct delivery factors, one existing pond,
one existing shared pump, a leveling instance, a proposed pond, and one shared
repair. Weekly warabandi turns, duration proportional to area.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from aabflow.domain.calendar import PKT

FIXTURE_ID = "fixture-science"
FIXTURE_VERSION = "test-v1"
LABEL = "synthetic science fixture (tests only, not pilot evidence)"

FIELDS = [
    # field_id, area_ha, node, group, soil
    ("fx-f1", 2.0, "fx-n-head", "head", "fx-soil-siltloam"),
    ("fx-f2", 1.5, "fx-n-mid", "middle", "fx-soil-loam"),
    ("fx-f3", 2.0, "fx-n-tail", "tail", "fx-soil-siltloam"),
    ("fx-f4", 1.0, "fx-n-tail", "tail", "fx-soil-loam"),
]
RATE_M3_S = 0.04
HOURS_PER_HA = 2.5

SEASON_PLANTINGS = {
    "wheat-rabi-2026-27": (date(2026, 11, 15), 150),
    "wheat-rabi-2027-28": (date(2027, 11, 15), 150),
    "wheat-rabi-2024-25": (date(2024, 11, 15), 150),
    "cotton-kharif-2027": (date(2027, 5, 1), 180),
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def nodes() -> list[dict]:
    return [
        {"node_id": "fx-n-src", "kind": "source", "lon": 72.50, "lat": 30.80},
        {"node_id": "fx-n-mogha", "kind": "junction", "lon": 72.501, "lat": 30.799},
        {"node_id": "fx-n-head", "kind": "outlet", "lon": 72.502, "lat": 30.798},
        {"node_id": "fx-n-mid", "kind": "outlet", "lon": 72.503, "lat": 30.797},
        {"node_id": "fx-n-tail", "kind": "outlet", "lon": 72.504, "lat": 30.796},
    ]


def edges(closure: bool = True) -> list[dict]:
    src_closures = []
    if closure:
        for y in (2024, 2025, 2026, 2027):
            a = datetime(y, 12, 26, tzinfo=PKT)
            src_closures.append([_iso(a), _iso(a + timedelta(days=10))])
    return [
        {
            "edge_id": "fx-e-src",
            "upstream_node_id": "fx-n-src",
            "downstream_node_id": "fx-n-mogha",
            "geometry_ref": None,
            "delivery_factor": 0.95,
            "capacities": [
                {
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2029-01-01T00:00:00Z",
                    "max_rate_m3_s": 0.05,
                }
            ],
            "closures": src_closures,
            "reach_label": "distributary to mogha",
        },
        {
            "edge_id": "fx-e-head",
            "upstream_node_id": "fx-n-mogha",
            "downstream_node_id": "fx-n-head",
            "geometry_ref": None,
            "delivery_factor": 0.9,
            "reach_label": "head reach",
        },
        {
            "edge_id": "fx-e-mid",
            "upstream_node_id": "fx-n-head",
            "downstream_node_id": "fx-n-mid",
            "geometry_ref": None,
            "delivery_factor": 0.85,
            "reach_label": "middle reach",
        },
        {
            "edge_id": "fx-e-tail",
            "upstream_node_id": "fx-n-mid",
            "downstream_node_id": "fx-n-tail",
            "geometry_ref": None,
            "delivery_factor": 0.8,
            "reach_label": "tail reach",
        },
    ]


def roster(planting: date, days: int) -> list[dict]:
    out = []
    week0 = datetime(planting.year, planting.month, planting.day, 6, tzinfo=PKT)
    for k in range(days // 7):
        t = week0 + timedelta(days=7 * k)
        for fid, area, *_ in FIELDS:
            dur = timedelta(hours=HOURS_PER_HA * area)
            out.append(
                {
                    "window_id": f"{fid}-w{k:02d}",
                    "field_id": fid,
                    "outlet_node_id": "fx-n-mogha",
                    "start": _iso(t),
                    "end": _iso(t + dur),
                    "basis": "time",
                    "rate_m3_s": RATE_M3_S,
                    "accounting_boundary": "outlet",
                    "verification": "assumed",
                    "source_rule": "TEST FIXTURE weekly warabandi, head to tail, duration proportional to area",
                }
            )
            t += dur
    return out


def write_fixture_pilot(data_dir: Path, *, closure: bool = True) -> Path:
    d = data_dir / "pilots" / FIXTURE_ID / FIXTURE_VERSION
    d.mkdir(parents=True, exist_ok=True)
    (d / "FIXTURE_LABEL").write_text(LABEL)
    feats = []
    for fid, area, node, group, soil in FIELDS:
        feats.append(
            {
                "type": "Feature",
                "id": fid,
                "geometry": None,
                "properties": {
                    "field_id": fid,
                    "label": fid.upper(),
                    "geometry_ref": fid,
                    "gross_area_m2": area * 10000,
                    "gross_area_ha": area,
                    "soil_profile_id": soil,
                    "outlet_node_id": node,
                    "group": group,
                    "existing_application_efficiency": 0.6,
                },
            }
        )
    (d / "fields.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    (d / "network.json").write_text(json.dumps({"nodes": nodes(), "edges": edges(closure)}))
    (d / "roster.json").write_text(
        json.dumps({"seasons": {sid: roster(p, n) for sid, (p, n) in SEASON_PLANTINGS.items()}})
    )
    (d / "assets.json").write_text(
        json.dumps(
            [
                {
                    "asset_id": "fx-pond-f3",
                    "kind": "pond",
                    "existing": True,
                    "field_ids": ["fx-f3"],
                    "commissioned_at": "2020-01-01",
                    "usable_capacity_m3": 1500.0,
                    "surface_area_m2": 1000.0,
                    "footprint_m2": 1300.0,
                    "initial_inventory_m3": 200.0,
                    "seepage_m3_day": 2.0,
                    "k_evap": 1.0,
                    "rain_capture_fraction": 1.0,
                    "max_release_m3_day": 1500.0,
                },
                {
                    "asset_id": "fx-pump-1",
                    "kind": "pump",
                    "existing": True,
                    "field_ids": ["fx-f2", "fx-f3", "fx-f4"],
                    "node_id": "fx-n-tail",
                    "commissioned_at": "2018-01-01",
                    "max_rate_m3_h": 30.0,
                    "seasonal_cap_m3": 6000.0,
                    "cost_per_m3_pkr": "4.50",
                    "head_m": 20.0,
                    "efficiency": 0.5,
                },
            ]
        )
    )
    vol, surf, foot = 375.0, 250.0, 420.0  # 0.5 irrigation x 75 mm on 1 ha
    (d / "interventions.json").write_text(
        json.dumps(
            {
                "types": [
                    {
                        "type_id": "leveling",
                        "category": "leveling",
                        "effect_model": "appeff",
                        "effect_model_version": "1",
                    },
                    {
                        "type_id": "pond",
                        "category": "pond",
                        "effect_model": "storage",
                        "effect_model_version": "1",
                    },
                    {
                        "type_id": "repair",
                        "category": "shared_repair",
                        "effect_model": "eta",
                        "effect_model_version": "1",
                    },
                    {
                        "type_id": "pump",
                        "category": "pump_supplement",
                        "effect_model": "gw",
                        "effect_model_version": "1",
                    },
                ],
                "instances": [
                    {
                        "instance_id": "fx:fx-f1:leveling",
                        "type_id": "leveling",
                        "category": "leveling",
                        "target_ids": ["fx-f1"],
                        "parameters": {"application_efficiency_after": 0.75},
                        "capex_pkr": 40000,
                        "lead_time_days": 20,
                        "procurement_delay_days": 5,
                    },
                    {
                        "instance_id": "fx:fx-f4:pond-small",
                        "type_id": "pond",
                        "category": "pond",
                        "target_ids": ["fx-f4"],
                        "mutually_exclusive_group": "fx-f4:pond",
                        "parameters": {
                            "irrigations_held": 0.5,
                            "usable_capacity_m3": vol,
                            "surface_area_m2": surf,
                            "footprint_m2": foot,
                            "seepage_m3_day": 0.5,
                            "k_evap": 1.0,
                        },
                        "capex_pkr": 150000,
                        "lead_time_days": 90,
                        "procurement_delay_days": 10,
                    },
                    {
                        "instance_id": "fx:fx-e-mid:repair",
                        "type_id": "repair",
                        "category": "shared_repair",
                        "target_ids": ["fx-e-mid"],
                        "shared": True,
                        "parameters": {"delivery_factor_after": 0.95, "downtime_days": 10},
                        "capex_pkr": 500000,
                        "lead_time_days": 120,
                        "procurement_delay_days": 10,
                    },
                    {
                        "instance_id": "fx:fx-pump-1:supplement",
                        "type_id": "pump",
                        "category": "pump_supplement",
                        "target_ids": ["fx-pump-1"],
                        "capex_pkr": 0,
                    },
                ],
            }
        )
    )
    (d / "soils.json").write_text(
        json.dumps(
            [
                {
                    "soil_profile_id": "fx-soil-siltloam",
                    "engine_soil_type": "SiltLoam",
                    "archetype": "silt-loam",
                    "initial_water": "pct_taw:50",
                },
                {
                    "soil_profile_id": "fx-soil-loam",
                    "engine_soil_type": "Loam",
                    "archetype": "loam",
                    "initial_water": "pct_taw:50",
                },
            ]
        )
    )
    (d / "service_reference.json").write_text(json.dumps([]))
    return d


# --------------------------------------------------------------------------- test environment


def synthetic_weather_frame(start: date, end: date, precip: float, et0: float):
    """TEST FIXTURE weather (constant daily values), never used for real science runs."""
    import pandas as pd

    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    return pd.DataFrame(
        {
            "Date": dates.astype("datetime64[ns]"),
            "MinTemp": [8.0] * n,
            "MaxTemp": [22.0] * n,
            "Precipitation": [precip] * n,
            "ReferenceET": [et0] * n,
        }
    )


def write_synthetic_weather(data_dir: Path) -> None:
    """Publish synthetic dry/typical/wet scenarios for every season + supply profiles (tests only)."""
    from aabflow.science import crop_profiles, scenarios
    from aabflow.science.weather import store_weather

    rows = []
    for s in crop_profiles.SEASONS.values():
        for wid, p, e in (("dry", 0.0, 4.0), ("typical", 0.5, 3.5), ("wet", 3.0, 3.0)):
            sha, _ = store_weather(synthetic_weather_frame(s.sim_start, s.sim_end, p, e))
            rows.append(
                {
                    "weather_scenario_id": wid,
                    "season_id": s.season_id,
                    "label": f"TEST FIXTURE {wid}",
                    "analog_season_start": s.sim_start.isoformat(),
                    "weather_series_id": "fixture-synthetic",
                    "transformed_sha256": sha,
                    "is_typical": wid == "typical",
                    "selection_basis": "TEST FIXTURE constant synthetic weather",
                    "kind": "analog",
                }
            )
    doc = {
        "default_grid_cell": "fixture",
        "pilot_grid_cells": {FIXTURE_ID: "fixture"},
        "grid_cells": {"fixture": {"scenarios": rows}},
        "scenarios": rows,
    }
    lib = data_dir / "libraries"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "weather_scenarios.json").write_text(json.dumps(doc))
    scenarios.publish_supply([FIXTURE_ID])


def science_env(tmp_path: Path, monkeypatch, *, closure: bool = True, weather: bool = True) -> Path:
    """Point science/water at an isolated data dir containing the labelled fixture pilot."""
    from aabflow.science import paths, soils
    from aabflow.water import ledger

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    write_fixture_pilot(tmp_path, closure=closure)
    soils.refresh()
    ledger._cached_context.cache_clear()
    ledger._policies_cached.cache_clear()
    if weather:
        write_synthetic_weather(tmp_path)
    return tmp_path
