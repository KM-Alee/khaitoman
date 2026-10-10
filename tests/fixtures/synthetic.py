"""TEST FIXTURE: synthetic pilot package, season catalog and candidate library.

Everything in this module is invented for unit/integration tests of the API and
optimizer. It is labelled "TEST FIXTURE" in every record, lives only under
``tests/`` and is written into a temporary data directory; no production code
path imports it. Yields, costs and water amounts are arbitrary test numbers,
never field predictions.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from aabflow.domain.hashes import content_hash, file_sha256

LABEL = "TEST FIXTURE"
PILOT_ID = "fixture-a"
VERSION = "test-v1"
SEASON_ID = "fixture-wheat-season"
SEASON_LATE = "fixture-late-season"
FIELDS = ["fixture-a:f1", "fixture-a:f2", "fixture-a:f3", "fixture-a:f4"]
GROUPS = {
    "fixture-a:f1": "head",
    "fixture-a:f2": "middle",
    "fixture-a:f3": "tail",
    "fixture-a:f4": "tail",
}
AREAS_HA = {"fixture-a:f1": 1.2, "fixture-a:f2": 1.0, "fixture-a:f3": 0.9, "fixture-a:f4": 1.1}
OUTLET = {
    "fixture-a:f1": "o-head",
    "fixture-a:f2": "o-head",
    "fixture-a:f3": "o-tail",
    "fixture-a:f4": "o-tail",
}
REPAIR = "fixture-a:e-tail:repair"
LEVEL = "fixture-a:f1:level"
POND_S = "fixture-a:f3:pond-small"
POND_L = "fixture-a:f3:pond-large"
DECISION = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
PLANTING = date(2026, 11, 15)
WEATHER = ["dry", "typical", "wet"]
SUPPLY = ["nominal-roster-v1", "shortage-22pct-v1", "interruption-14d-v1"]
SHA0 = "0" * 64


def _w(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))


def _png(path: Path, w: int = 4, h: int = 4) -> None:
    raw = b"".join(b"\x00" + bytes([40, 120, 60] * w) for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _square(lon: float, lat: float, d: float = 0.0008) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]
        ],
    }


def build_pilot(data_dir: Path, pilot_id: str = PILOT_ID, version: str = VERSION) -> Path:
    d = Path(data_dir) / "pilots" / pilot_id / version
    bbox = [72.40, 30.70, 72.41, 30.71]
    features = []
    for i, fid in enumerate(FIELDS):
        props = {
            "field_id": fid,
            "label": f"{LABEL} field {i + 1}",
            "geometry_ref": fid,
            "gross_area_m2": AREAS_HA[fid] * 10000,
            "gross_area_ha": AREAS_HA[fid],
            "soil_profile_id": "fixture-loam",
            "outlet_node_id": OUTLET[fid],
            "group": GROUPS[fid],
            "source_model_ids": [f"delineate:{i}"],
            "evidence_ids": ["ev-fixture-fields"],
        }
        features.append(
            {
                "type": "Feature",
                "id": fid,
                "properties": props,
                "geometry": _square(72.401 + i * 0.002, 30.701),
            }
        )
    _w(d / "fields.geojson", {"type": "FeatureCollection", "features": features})
    _w(d / "fields_raw.geojson", {"type": "FeatureCollection", "features": features})
    _w(
        d / "aoi.geojson",
        {"type": "Feature", "properties": {}, "geometry": _square(72.40, 30.70, 0.01)},
    )
    _w(
        d / "canals.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "osm:way/1",
                    "properties": {"waterway": "canal", "label": LABEL},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[72.40, 30.70], [72.405, 30.705]],
                    },
                }
            ],
        },
    )
    nodes = [
        {"node_id": "src", "kind": "source", "lon": 72.40, "lat": 30.70},
        {"node_id": "j1", "kind": "junction", "lon": 72.405, "lat": 30.705},
        {"node_id": "o-head", "kind": "outlet", "lon": 72.406, "lat": 30.706},
        {"node_id": "o-tail", "kind": "outlet", "lon": 72.409, "lat": 30.709},
    ]
    edges = [
        {
            "edge_id": "e-main",
            "upstream_node_id": "src",
            "downstream_node_id": "j1",
            "geometry_ref": "osm:way/1",
            "source_feature_ids": ["osm:way/1"],
            "delivery_factor": 0.95,
            "reach_label": "main",
        },
        {
            "edge_id": "e-head",
            "upstream_node_id": "j1",
            "downstream_node_id": "o-head",
            "geometry_ref": None,
            "delivery_factor": 0.9,
            "reach_label": "head",
        },
        {
            "edge_id": "e-tail",
            "upstream_node_id": "j1",
            "downstream_node_id": "o-tail",
            "geometry_ref": None,
            "delivery_factor": 0.65,
            "reach_label": "tail",
        },
    ]
    _w(d / "network.json", {"nodes": nodes, "edges": edges})
    windows = []
    for i, fid in enumerate(FIELDS):
        for turn in range(3):
            start = datetime(2026, 12, 1, tzinfo=UTC) + timedelta(days=21 * turn, hours=6 * i)
            windows.append(
                {
                    "window_id": f"{fid}:w{turn}",
                    "field_id": fid,
                    "outlet_node_id": OUTLET[fid],
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=6)).isoformat(),
                    "basis": "time",
                    "rate_m3_s": 0.03,
                    "source_rule": f"{LABEL} roster",
                }
            )
    _w(d / "roster.json", {"seasons": {SEASON_ID: windows, SEASON_LATE: windows}})
    _w(
        d / "service_reference.json",
        [
            {
                "field_id": fid,
                "season_id": SEASON_ID,
                "reference_receipt_m3": 3 * 0.03 * 6 * 3600,
                "basis": "time",
            }
            for fid in FIELDS
        ],
    )
    _w(
        d / "assets.json",
        [
            {
                "asset_id": "fixture-a:pond-existing",
                "kind": "pond",
                "existing": True,
                "field_ids": ["fixture-a:f2"],
                "commissioned_at": "2020-01-01",
                "usable_capacity_m3": 400,
                "surface_area_m2": 300,
                "footprint_m2": 400,
                "evidence_ids": ["ev-fixture-assets"],
            },
            {
                "asset_id": "fixture-a:pump-shared",
                "kind": "pump",
                "existing": True,
                "field_ids": ["fixture-a:f3", "fixture-a:f4"],
                "node_id": "o-tail",
                "commissioned_at": "2019-01-01",
                "max_rate_m3_h": 30,
                "seasonal_cap_m3": 1500,
                "cost_per_m3_pkr": "12.5",
                "evidence_ids": ["ev-fixture-assets"],
            },
        ],
    )
    _w(
        d / "interventions.json",
        {
            "types": [
                {
                    "type_id": "leveling-v1",
                    "category": "leveling",
                    "effect_model": "app_eff",
                    "effect_model_version": "1",
                },
                {
                    "type_id": "pond-v1",
                    "category": "pond",
                    "effect_model": "storage",
                    "effect_model_version": "1",
                },
                {
                    "type_id": "repair-v1",
                    "category": "shared_repair",
                    "effect_model": "edge_factor",
                    "effect_model_version": "1",
                },
                {
                    "type_id": "pump-v1",
                    "category": "pump_supplement",
                    "effect_model": "gw",
                    "effect_model_version": "1",
                },
            ],
            "instances": [
                {
                    "instance_id": LEVEL,
                    "type_id": "leveling-v1",
                    "category": "leveling",
                    "target_ids": ["fixture-a:f1"],
                    "capex_pkr": 60000,
                    "lead_time_days": 14,
                },
                {
                    "instance_id": POND_S,
                    "type_id": "pond-v1",
                    "category": "pond",
                    "target_ids": ["fixture-a:f3"],
                    "mutually_exclusive_group": "fixture-a:f3:pond",
                    "capex_pkr": 150000,
                    "seasonal_opex_pkr": 2000,
                    "lead_time_days": 20,
                    "parameters": {"footprint_m2": 500},
                },
                {
                    "instance_id": POND_L,
                    "type_id": "pond-v1",
                    "category": "pond",
                    "target_ids": ["fixture-a:f3"],
                    "mutually_exclusive_group": "fixture-a:f3:pond",
                    "capex_pkr": 260000,
                    "seasonal_opex_pkr": 3000,
                    "lead_time_days": 20,
                    "parameters": {"footprint_m2": 900},
                },
                {
                    "instance_id": REPAIR,
                    "type_id": "repair-v1",
                    "category": "shared_repair",
                    "target_ids": ["e-tail"],
                    "capex_pkr": 200000,
                    "lead_time_days": 30,
                    "shared": True,
                    "parameters": {"delivery_factor_after": 0.9},
                },
                {
                    "instance_id": "fixture-a:f4:pond-late",
                    "type_id": "pond-v1",
                    "category": "pond",
                    "target_ids": ["fixture-a:f4"],
                    "capex_pkr": 100000,
                    "lead_time_days": 200,
                },
                {
                    "instance_id": "fixture-a:f2:level-nocost",
                    "type_id": "leveling-v1",
                    "category": "leveling",
                    "target_ids": ["fixture-a:f2"],
                    "capex_pkr": 0,
                },
            ],
        },
    )
    _w(
        d / "soils.json",
        [{"soil_profile_id": "fixture-loam", "engine_soil_type": "Loam", "archetype": "loam"}],
    )
    _w(
        d / "evidence.json",
        [
            {
                "evidence_id": "ev-fixture-fields",
                "source_title": f"{LABEL} reviewed field polygons",
                "kind": "derived",
                "limitations": ["synthetic test geometry"],
            },
            {
                "evidence_id": "ev-fixture-assets",
                "source_title": f"{LABEL} pond and shared pump record",
                "kind": "assumption",
                "limitations": ["invented for tests"],
            },
            {
                "evidence_id": "ev-fixture-scene",
                "source_title": f"{LABEL} Sentinel-2 display image",
                "kind": "observed_remote_sensing",
                "source_asset_id": "S2-TEST",
            },
        ],
    )
    _png(d / "imagery" / "S2-TEST.png")
    corners = [[72.40, 30.71], [72.41, 30.71], [72.41, 30.70], [72.40, 30.70]]
    _w(
        d / "imagery" / "S2-TEST.json",
        {"scene_id": "S2-TEST", "corners_wgs84": corners, "evidence_id": "ev-fixture-scene"},
    )
    _png(d / "terrain" / "dem.png")
    _w(
        d / "terrain" / "dem.json",
        {
            "bounds": bbox,
            "width": 4,
            "height": 4,
            "min_m": 160.0,
            "max_m": 171.0,
            "encoding": "terrarium",
            "image_ref": "terrain/dem.png",
        },
    )
    _w(d / "resource_status.json", {"fixture": {"docs_checked": LABEL}})
    pilot = {
        "pilot_id": pilot_id,
        "pilot_version": version,
        "name": f"{LABEL} pilot A",
        "geographic_name_basis": LABEL,
        "aoi_geojson_ref": "aoi.geojson",
        "aoi_bbox": bbox,
        "aoi_area_m2": 1.1e6,
        "metric_crs": "EPSG:32643",
        "state": "published",
        "review_flags": {"geography_reviewed": True, "topology_structurally_valid": True},
        "imagery": [
            {
                "scene_id": "S2-TEST",
                "acquired_at": "2026-02-01T05:30:00Z",
                "aoi_valid_fraction": 0.98,
                "display_image_ref": "imagery/S2-TEST.png",
                "display_corners_wgs84": corners,
                "evidence_id": "ev-fixture-scene",
            }
        ],
        "created_at": "2026-10-10T00:00:00Z",
    }
    _w(d / "pilot.json", pilot)
    files = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            rel = p.relative_to(d).as_posix()
            files.append(
                {
                    "path": rel,
                    "size_bytes": p.stat().st_size,
                    "sha256": file_sha256(p),
                    "kind": p.suffix[1:],
                }
            )
    _w(
        d / "manifest.json",
        {
            "pilot_id": pilot_id,
            "pilot_version": version,
            "state": "published",
            "files": files,
            "source_ids": ["osm:way/1"],
            "licenses": ["test"],
            "processing_versions": {"fixture": "1"},
            "generated_at": "2026-10-10T00:00:00Z",
        },
    )
    idx = Path(data_dir) / "pilots" / "index.json"
    rows = json.loads(idx.read_text()) if idx.exists() else []
    rows.append({"pilot_id": pilot_id, "pilot_version": version, "name": f"{LABEL} pilot A"})
    _w(idx, rows)
    return d


def state_id(w: str, s: str) -> str:
    return f"{w}__{s}"


def build_catalog(data_dir: Path) -> None:
    lib = Path(data_dir) / "libraries"
    seasons = [
        {
            "season_id": SEASON_ID,
            "crop": "wheat",
            "crop_profile_id": "fixture-wheat",
            "start": "2026-11-01",
            "end": "2027-04-30",
            "planning_modes": ["season_response", "capital_planning"],
            "planting_date": PLANTING.isoformat(),
            "decision_at": DECISION.isoformat(),
            "label": f"{LABEL} wheat",
        },
        {
            "season_id": SEASON_LATE,
            "crop": "cotton",
            "crop_profile_id": "fixture-cotton",
            "start": "2027-04-01",
            "end": "2027-10-31",
            "planning_modes": ["capital_planning"],
            "planting_date": "2027-05-01",
            "decision_at": DECISION.isoformat(),
            "label": f"{LABEL} cotton",
        },
    ]
    _w(lib / "seasons.json", seasons)
    _w(lib / "crop_profiles.json", [])
    scen = []
    for sid in (SEASON_ID, SEASON_LATE):
        for w in WEATHER:
            scen.append(
                {
                    "weather_scenario_id": w,
                    "season_id": sid,
                    "label": f"{LABEL} {w}",
                    "analog_season_start": "2015-11-01",
                    "weather_series_id": "fixture-series",
                    "transformed_sha256": content_hash([sid, w]),
                    "is_typical": w == "typical",
                    "selection_basis": LABEL,
                }
            )
    _w(
        lib / "weather_scenarios.json",
        {"scenarios": scen, "pilot_grid_cells": {}, "grid_cells": {}},
    )
    profiles = [
        {
            "supply_profile_id": "nominal-roster-v1",
            "base_profile_hash": SHA0,
            "label": "nominal",
            "resolved_hash": content_hash("n"),
        },
        {
            "supply_profile_id": "shortage-22pct-v1",
            "base_profile_hash": SHA0,
            "label": "22% shortage",
            "transformations": [
                {"transformation_id": "t-short", "kind": "absolute_multiplier", "multiplier": 0.78}
            ],
            "resolved_hash": content_hash("s"),
        },
        {
            "supply_profile_id": "interruption-14d-v1",
            "base_profile_hash": SHA0,
            "label": "14 day closure",
            "transformations": [
                {
                    "transformation_id": "t-int",
                    "kind": "closure",
                    "start": "2026-12-20T00:00:00Z",
                    "end": "2027-01-03T00:00:00Z",
                }
            ],
            "resolved_hash": content_hash("i"),
        },
    ]
    sets = []
    for sid in (SEASON_ID, SEASON_LATE):
        sets.append(
            {
                "uncertainty_set_id": f"{sid}:release-9",
                "pilot_id": PILOT_ID,
                "season_id": sid,
                "states": [
                    {
                        "state_id": state_id(w, s),
                        "weather_scenario_id": w,
                        "supply_profile_id": s,
                        "resolved_supply_profile_hash": content_hash([s]),
                    }
                    for w in WEATHER
                    for s in SUPPLY
                ],
            }
        )
    _w(
        lib / "supply.json",
        {
            "version": "fixture",
            "supply_profile_ids": SUPPLY,
            "seasons": {SEASON_ID: {"generic": profiles}, SEASON_LATE: {"generic": profiles}},
            "uncertainty_sets": sets,
        },
    )


def build_all(data_dir: Path) -> Path:
    build_catalog(data_dir)
    return build_pilot(data_dir)
