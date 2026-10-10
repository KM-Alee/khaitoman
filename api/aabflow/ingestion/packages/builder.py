"""Pilot package assembly (STREAMS.md file contract, T2.6, T3.4).

``build_package`` turns processed sources + reviewed fields into every file of
``data/pilots/<pilot_id>/<pilot_version>/`` (written to a staging directory),
including ``evidence.json``, ``resource_status.json`` and ``manifest.json``.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import rasterio
from PIL import Image, ImageDraw
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from shapely.geometry import Point, mapping, shape

from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.schemas import (
    CapacityInterval,
    EvidenceKind,
    EvidenceRecord,
    Field_,
    ImageryRef,
    ManifestFile,
    PackageState,
    Pilot,
    PilotManifest,
    ReviewFlags,
    VerificationState,
    WeatherSeries,
)
from aabflow.domain.schemas.evidence import AssumptionRange

from ..aoi import DISCOVERY_EXTENT, Aoi, to_metric
from ..common import INGESTION_VERSION, dumps, iso, read_json, utc_now, write_json
from ..grain import reader as grain
from ..imagery import delineate
from ..imagery.display import STRETCH_ID
from ..osm import overpass
from ..review.fields import REVIEW_RULES_VERSION
from ..stac import sentinel2 as s2
from ..terrain import copdem
from ..weather import openmeteo
from . import network as netmod
from . import operations as ops

PACKAGE_FORMAT_VERSION = "aabflow-pilot-package-1"
MANIFEST_EXCLUDE = {"manifest.json"}


@dataclass
class ReviewedField:
    field_id: str
    label: str
    geometry_wgs84: dict
    area_m2: float
    source_model_ids: list[str]
    actions: list[str]


def kind_of(path: str) -> str:
    if path.startswith("imagery/") and path.endswith(".webp"):
        return "display_image"
    if path.startswith("imagery/"):
        return "imagery_metadata"
    if path.startswith("terrain/"):
        return "terrain"
    if path.startswith("weather/") and path.endswith(".parquet"):
        return "weather_normalized"
    if path.startswith("weather/index"):
        return "weather_index"
    if path.startswith("weather/"):
        return "weather_raw"
    return {
        "pilot.json": "pilot",
        "aoi.geojson": "aoi",
        "fields.geojson": "fields",
        "fields_raw.geojson": "fields_raw",
        "fields_raw.gpkg": "fields_raw_gpkg",
        "review_log.json": "review_log",
        "review_overlay.png": "review_overlay",
        "canals.geojson": "canals",
        "network.json": "network",
        "roster.json": "roster",
        "service_reference.json": "service_reference",
        "assets.json": "assets",
        "interventions.json": "interventions",
        "soils.json": "soils",
        "evidence.json": "evidence",
        "resource_status.json": "resource_status",
    }.get(path, "other")


def field_ndvi_stats(ndvi_tif: Path, fields: list[ReviewedField]) -> dict[str, dict]:
    with rasterio.open(ndvi_tif) as src:
        arr = src.read(1)
        out = {}
        for f in fields:
            g = transform_geom("EPSG:4326", src.crs.to_string(), f.geometry_wgs84)
            inside = geometry_mask([g], out_shape=arr.shape, transform=src.transform, invert=True)
            vals = arr[inside]
            fin = vals[np.isfinite(vals)]
            out[f.field_id] = {
                "pixels": int(inside.sum()),
                "valid_fraction": round(float(fin.size / max(1, vals.size)), 4),
                "mean": round(float(fin.mean()), 4) if fin.size else None,
                "median": round(float(np.median(fin)), 4) if fin.size else None,
                "status": "available" if fin.size else "unavailable",
            }
    return out


def render_overlay(
    display_png: Path,
    corners,
    raw_fc: dict,
    fields: list[ReviewedField],
    out: Path,
    scale: int = 3,
    canals_fc: dict | None = None,
    aoi_geom: dict | None = None,
):
    """Review overlay: raw model polygons (yellow) and reviewed fields (cyan, labelled)."""
    img = Image.open(display_png).convert("RGBA")
    w0, h0 = img.size
    img = img.resize((w0 * scale, h0 * scale), Image.NEAREST)
    W, H = img.size
    (west, north), _, (east, south), _ = corners
    import math as _m

    def merc_y(lat):
        return _m.log(_m.tan(_m.pi / 4 + _m.radians(lat) / 2))

    yn, ys = merc_y(north), merc_y(south)

    def px(lon, lat):
        return ((lon - west) / (east - west) * W, (yn - merc_y(lat)) / (yn - ys) * H)

    dr = ImageDraw.Draw(img)

    def rings(geom):
        g = shape(geom)
        polys = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
        for p in polys:
            if p.geom_type == "Polygon":
                yield list(p.exterior.coords)

    for f in raw_fc["features"]:
        for ring in rings(f["geometry"]):
            dr.line([px(*c) for c in ring], fill=(255, 220, 0, 255), width=1)
    for f in (canals_fc or {}).get("features", []):
        g = shape(f["geometry"])
        lines = [g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))
        for ln in lines:
            dr.line([px(*c) for c in ln.coords], fill=(40, 120, 255, 255), width=3)
    if aoi_geom:
        for ring in rings(aoi_geom):
            dr.line([px(*c) for c in ring], fill=(255, 255, 255, 255), width=2)
    for f in fields:
        for ring in rings(f.geometry_wgs84):
            dr.line([px(*c) for c in ring], fill=(0, 255, 255, 255), width=3)
        c = shape(f.geometry_wgs84).representative_point()
        x, y = px(c.x, c.y)
        dr.text((x - 8, y - 6), f.label.split("-")[-1], fill=(255, 255, 255, 255))
    img.convert("RGB").save(out, format="PNG")


def _ev(**kw) -> EvidenceRecord:
    return EvidenceRecord(**kw)


def build_package(
    *,
    stage_dir: Path,
    processed: Path,
    bundle_manifest: dict,
    bundle_ref: str,
    aoi: Aoi,
    pilot_id: str,
    pilot_version: str,
    name: str,
    geographic_name_basis: str,
    fields: list[ReviewedField],
    review_state: dict,
    parent_canal_id: str,
    created_at: datetime | None = None,
    warabandi: Literal["declared_cca", "selected_area"] = "declared_cca",
) -> Path:
    """Write the complete package into ``stage_dir`` and return it."""
    now = created_at or utc_now()
    stage_dir.mkdir(parents=True, exist_ok=False)
    P = stage_dir
    crs = aoi.metric_crs
    proc = read_json(processed / "process_result.json")
    ev: list[EvidenceRecord] = []
    bfiles = {f["path"]: f for f in bundle_manifest["files"]}

    # --- AOI ---------------------------------------------------------------
    write_json(
        P / "aoi.geojson",
        aoi.feature_collection(
            {
                "pilot_id": pilot_id,
                "name": name,
                "area_m2": round(aoi.area_m2, 2),
                "metric_crs": aoi.metric_crs_id,
            }
        ),
    )
    ev.append(
        _ev(
            evidence_id="ev:aoi",
            source_title=f"{name} AOI selection",
            kind=EvidenceKind.derived,
            verification_state=VerificationState.artifact_checked,
            retrieved_at=now,
            geographic_scope=f"bbox {aoi.bbox}",
            transformation=geographic_name_basis,
            parent_evidence_ids=[
                "ev:discovery-extent",
                "ev:osm-canals",
                f"ev:s2:{proc['imagery'][0]['scene_id']}",
            ],
            units="EPSG:4326; area m² in " + aoi.metric_crs_id,
            method_version=INGESTION_VERSION,
            limitations=[
                (
                    "AOI chosen for visible parcels and mapped canal context; not an "
                    "administrative or command boundary"
                )
            ],
        )
    )
    ev.append(
        _ev(
            evidence_id="ev:discovery-extent",
            source_title="Mungi hydrology study search extent",
            kind=EvidenceKind.literature,
            source_url=DISCOVERY_EXTENT["source"],
            geographic_scope=f"bbox {DISCOVERY_EXTENT['bbox']} ({DISCOVERY_EXTENT['scope']})",
            verification_state=VerificationState.unchecked,
            allowed_use="AOI discovery only; does not identify the pilot boundary or reach",
            limitations=[
                "Coordinates transcribed from the specification (T2.2); paper not re-read"
            ],
        )
    )

    # --- imagery -------------------------------------------------------------
    (P / "imagery").mkdir()
    imagery_refs: list[ImageryRef] = []
    ndvi_by_scene = {}
    for rec in proc["imagery"]:
        sid = rec["scene_id"]
        shutil.copyfile(processed / rec["image_ref"], P / rec["image_ref"])
        eid = f"ev:s2:{sid}"
        item_path = f"stac/items/{sid}.json"
        meta = {
            k: rec[k]
            for k in (
                "scene_id",
                "collection",
                "acquired_at",
                "image_ref",
                "corners_wgs84",
                "bounds_wgs84",
                "width",
                "height",
                "display_crs",
                "resolution_m",
                "aoi_valid_fraction",
                "scene_cloud_cover",
                "scl_histogram_aoi",
                "scl_invalid_classes",
                "stretch",
                "reflectance_offset_check",
                "label",
                "source_grid",
            )
        }
        meta["evidence_id"] = eid
        meta["ndvi_ref"] = f"imagery/{sid}.ndvi.json"
        write_json(P / f"imagery/{sid}.json", meta)
        stats = field_ndvi_stats(processed / rec["ndvi"]["ref"], fields)
        ndvi_by_scene[sid] = stats
        write_json(
            P / f"imagery/{sid}.ndvi.json",
            {
                "scene_id": sid,
                "acquired_at": rec["acquired_at"],
                "method": rec["ndvi"]["method"],
                "aoi": {
                    k: rec["ndvi"][k] for k in ("aoi_mean", "aoi_median", "aoi_valid_fraction")
                },
                "fields": stats,
                "interpretation": rec["ndvi"]["interpretation"],
                "evidence_id": f"ev:ndvi:{sid}",
            },
        )
        imagery_refs.append(
            ImageryRef(
                scene_id=sid,
                collection=rec["collection"],
                acquired_at=datetime.fromisoformat(rec["acquired_at"]),
                aoi_valid_fraction=min(1.0, rec["aoi_valid_fraction"]),
                display_image_ref=rec["image_ref"],
                display_corners_wgs84=[tuple(c) for c in rec["corners_wgs84"]],
                resolution_m=10.0,
                evidence_id=eid,
            )
        )
        ev.append(
            _ev(
                evidence_id=eid,
                source_title=f"Sentinel-2 L2A scene {sid}",
                kind=EvidenceKind.observed_remote_sensing,
                verification_state=VerificationState.artifact_checked,
                source_url=bfiles[item_path]["source_url"],
                source_asset_id=sid,
                retrieved_at=bfiles[item_path]["retrieved_at"],
                source_period=rec["acquired_at"],
                geographic_scope=f"COG windows {rec['source_grid']['width']}x{rec['source_grid']['height']} px "
                f"in {rec['source_grid']['crs']}",
                license_id=s2.LICENSE_ID,
                raw_sha256=bfiles[item_path]["sha256"],
                transformation=f"bounded COG window reads of {', '.join(sorted(rec['assets']))}; "
                f"SCL classes {rec['scl_invalid_classes']} invalid; AOI valid fraction "
                f"{rec['aoi_valid_fraction']:.4f}; {rec['reflectance_offset_check']['decision']}",
                units="reflectance (scale 1e-4)",
                method_version=INGESTION_VERSION,
                limitations=[
                    "10 m sampling; parcel boundaries below ~2 pixels are not resolved",
                    "single acquisition date; clouds screened by SCL only",
                ],
            )
        )
        ev.append(
            _ev(
                evidence_id=f"ev:s2-display:{sid}",
                source_title=f"Display image {sid}",
                kind=EvidenceKind.derived,
                parent_evidence_ids=[eid],
                transformation=f"stretch {STRETCH_ID}; reprojected to EPSG:3857 north-up; WGS84 corners",
                method_version=STRETCH_ID,
                allowed_use="map display only; not reflectance data",
            )
        )
        ev.append(
            _ev(
                evidence_id=f"ev:ndvi:{sid}",
                source_title=f"NDVI observation {sid}",
                kind=EvidenceKind.derived,
                parent_evidence_ids=[eid],
                transformation=rec["ndvi"]["method"],
                units="NDVI (unitless)",
                allowed_use="observation context; never water stress, crop identity or yield",
            )
        )

    # --- canals ----------------------------------------------------------------
    shutil.copyfile(processed / "canals.geojson", P / "canals.geojson")
    canals = read_json(P / "canals.geojson")
    osm_f = bfiles["osm/overpass.json"]
    ev.append(
        _ev(
            evidence_id="ev:osm-canals",
            source_title="OpenStreetMap waterways (Overpass bounded query)",
            kind=EvidenceKind.public_geography,
            verification_state=VerificationState.artifact_checked,
            source_url=overpass.OVERPASS_URL,
            retrieved_at=osm_f["retrieved_at"],
            source_period=f"OSM base {canals['properties'].get('osm_base_timestamp')}",
            geographic_scope="AOI bbox + 0.01°",
            license_id=overpass.LICENSE_ID,
            raw_sha256=osm_f["sha256"],
            transformation="ways with waterway=canal|ditch|drain → GeoJSON; ids osm:way/<id>; tags kept",
            method_version=INGESTION_VERSION,
            limitations=[
                "minor watercourses are incompletely mapped in rural Punjab",
                "geometry/classification only; no hydraulic capacity or connectivity",
            ],
        )
    )
    gsrc = bundle_manifest["sources"].get("grain", {})
    if "grain/pakistan_GRAIN_v.1.0.parquet" in bfiles:
        gf = bfiles["grain/pakistan_GRAIN_v.1.0.parquet"]
        ev.append(
            _ev(
                evidence_id="ev:grain",
                source_title="GRAIN v1.0 Pakistan canals (GeoParquet member)",
                kind=EvidenceKind.public_geography,
                verification_state=VerificationState.artifact_checked,
                source_url=grain.ZIP_URL,
                retrieved_at=gf["retrieved_at"],
                license_id=grain.LICENSE_ID,
                raw_sha256=gf["sha256"],
                transformation=f"zip member {gsrc.get('member')} via HTTP range reads; CRC-32 "
                f"{gsrc.get('crc32')} verified; clipped to AOI bbox + 0.01°: "
                f"{canals['properties']['grain'].get('rows_in_window', 0)} features",
                limitations=["archive-level MD5 not verifiable from a partial read"],
            )
        )

    # --- weather ------------------------------------------------------------------
    w = proc["weather"]
    (P / "weather").mkdir()
    shutil.copyfile(processed / w["raw_ref"], P / w["raw_ref"])
    shutil.copyfile(processed / w["normalized_ref"], P / w["normalized_ref"])
    wev = f"ev:weather:{w['weather_series_id']}"
    ws = WeatherSeries(
        weather_series_id=w["weather_series_id"],
        point_requested=tuple(w["point_requested"]),
        point_returned=tuple(w["point_returned"]),
        elevation_m=w["elevation_m"],
        start=date.fromisoformat(w["start"]),
        end=date.fromisoformat(w["end"]),
        source_model=w["source_model"],
        raw_ref=w["raw_ref"],
        normalized_ref=w["normalized_ref"],
        source_sha256=w["source_sha256"],
        normalized_sha256=w["normalized_sha256"],
        evidence_id=wev,
    )
    write_json(P / "weather/index.json", [ws.model_dump(mode="json")])
    ev.append(
        _ev(
            evidence_id=wev,
            source_title="Open-Meteo historical archive (historical gridded weather)",
            kind=EvidenceKind.gridded_reanalysis,
            verification_state=VerificationState.artifact_checked,
            source_url=w["source_url"],
            retrieved_at=w["retrieved_at"],
            source_period=f"{w['start']}..{w['end']} ({len(w['complete_years'])} complete years)",
            geographic_scope=f"grid point {w['point_returned']} (requested {w['point_requested']}), "
            f"elevation {w['elevation_m']} m",
            license_id=openmeteo.LICENSE_ID,
            raw_sha256=w["source_sha256"],
            transformation="daily temperature_2m_min/max, precipitation_sum, et0_fao_evapotranspiration "
            "→ MinTemp, MaxTemp, Precipitation, ReferenceET; complete daily index asserted; no "
            "interpolation",
            units="°C, mm/day",
            method_version=INGESTION_VERSION,
            limitations=[
                "reanalysis grid estimate (~10-25 km), not a station in each field",
                "pilots in the same cell share weather; no climate diversity claim",
            ],
        )
    )

    # --- terrain ------------------------------------------------------------------
    terrain_ref = None
    if proc.get("terrain"):
        (P / "terrain").mkdir()
        shutil.copyfile(processed / "terrain/dem.png", P / "terrain/dem.png")
        t = dict(proc["terrain"])
        t["evidence_id"] = "ev:dem"
        write_json(P / "terrain/dem.json", t)
        terrain_ref = "terrain/dem.json"
        dem_f = next(f for f in bundle_manifest["files"] if f["kind"] == "dem_window")
        ev.append(
            _ev(
                evidence_id="ev:dem",
                source_title="Copernicus DEM GLO-30 (AWS open data)",
                kind=EvidenceKind.observed_remote_sensing,
                verification_state=VerificationState.artifact_checked,
                source_url=t["source_url"],
                retrieved_at=dem_f["retrieved_at"],
                license_id=copdem.LICENSE_ID,
                raw_sha256=dem_f["sha256"],
                transformation="window read; Terrarium PNG encoding",
                units="m above EGM2008 geoid",
                allowed_use="3D display context only",
                limitations=["30 m DSM includes trees/buildings; does not verify flow direction"],
            )
        )

    # --- raw inference + review ------------------------------------------------------
    shutil.copyfile(processed / "fields_raw.geojson", P / "fields_raw.geojson")
    shutil.copyfile(processed / "fields_raw.gpkg", P / "fields_raw.gpkg")
    inf = proc["inference"]
    ev.append(
        _ev(
            evidence_id="ev:delineate",
            source_title="Delineate Anything v2 field-boundary inference",
            kind=EvidenceKind.model_output,
            verification_state=VerificationState.artifact_checked,
            source_url="https://github.com/Lavreniuk/Delineate-Anything",
            source_asset_id=delineate.CHECKPOINT_ID,
            retrieved_at=inf["finished_at"],
            raw_sha256=inf["gpkg_sha256"],
            parent_evidence_ids=[f"ev:s2:{proc['imagery'][0]['scene_id']}"],
            transformation=f"python delineate.py -b {inf['batch']} (upstream {inf['upstream_commit']}); "
            f"config {inf['base_config']} sha256 {inf['base_config_sha256']}; input sha256 "
            f"{inf['input_sha256']}; {inf['raw_polygons']} raw polygons; {inf['device']} wall "
            f"{inf['wall_seconds']} s; cache_hit={inf['cache_hit']}",
            method_version=f"checkpoint sha256 {next(iter((inf.get('checkpoints') or {}).values()), '')}",
            license_id="AGPL-3.0 (code); weights per Hugging Face model card",
            limitations=[
                "estimated boundaries, not ownership",
                "10 m imagery merges/splits small parcels",
            ],
        )
    )
    rs = review_state
    ev.append(
        _ev(
            evidence_id="ev:field-review",
            source_title="Field boundary review and selection",
            kind=EvidenceKind.derived,
            verification_state=VerificationState.artifact_checked,
            parent_evidence_ids=["ev:delineate"],
            transformation=dumps(rs["summary"]).strip(),
            method_version=REVIEW_RULES_VERSION,
            reviewer=rs.get("reviewer"),
            reviewed_at=rs.get("reviewed_at"),
            limitations=[
                "accuracy not estimated (no independent reference boundaries)",
                "selection favours clean parcels; not a population accuracy sample",
            ],
        )
    )
    shutil.copyfile(processed.parent / "review" / "review_log.json", P / "review_log.json")
    raw_fc = read_json(P / "fields_raw.geojson")
    prim = proc["imagery"][0]
    render_overlay(
        processed / prim["image_ref"],
        prim["corners_wgs84"],
        raw_fc,
        fields,
        P / "review_overlay.png",
    )

    # --- network ------------------------------------------------------------------
    parent = next(f for f in canals["features"] if f["id"] == parent_canal_id)
    sites = [
        netmod.FieldSite(f.field_id, tuple(shape(f.geometry_wgs84).centroid.coords[0]), f.area_m2)
        for f in fields
    ]
    closures = [c for c in (ops.closure_interval(s) for s in ops.SEASONS) if c]
    src_cap = [
        CapacityInterval(
            start=ops._pkt(s.start),
            end=ops._pkt(s.end + __import__("datetime").timedelta(days=1)),
            max_rate_m3_s=ops.ASSUMPTIONS["asm:source-capacity"].value,
        )
        for s in ops.SEASONS
    ]
    net = netmod.build_network(
        pilot_id,
        sites,
        parent,
        crs,
        closures,
        src_cap,
        evidence_ids={
            "parent": [
                "ev:osm-canals",
                "asm:parent-delivery",
                "asm:canal-closure",
                "asm:source-capacity",
                "ev:network",
            ],
            "reach": ["asm:reach-delivery", "ev:network"],
        },
    )
    write_json(
        P / "network.json",
        {
            "nodes": [n.model_dump(mode="json") for n in net.nodes],
            "edges": [e.model_dump(mode="json") for e in net.edges],
        },
    )
    ev.append(
        _ev(
            evidence_id="ev:network",
            source_title="Declared operational graph",
            kind=EvidenceKind.assumption,
            verification_state=VerificationState.artifact_checked,
            parent_evidence_ids=["ev:osm-canals"],
            transformation=f"{netmod.NETWORK_TEMPLATE}: " + " ".join(net.notes),
            method_version=netmod.NETWORK_TEMPLATE,
            assumption_range=AssumptionRange(
                low=netmod.FACTOR_RANGES["watercourse_reach"][0],
                high=netmod.FACTOR_RANGES["watercourse_reach"][1],
                unit="delivery factor",
            ),
            limitations=[
                "fractional-loss model; no hydraulics, backwater or gate response",
                "field-to-outlet associations are proposals, not legal connections",
            ],
        )
    )

    # --- soils, fields ----------------------------------------------------------------
    soils, field_soil = ops.build_soils(pilot_id, net)
    write_json(P / "soils.json", [s.model_dump(mode="json") for s in soils])
    feats = []
    for f in fields:
        rec = Field_(
            field_id=f.field_id,
            label=f.label,
            geometry_ref=f.field_id,
            geometry_version=1,
            gross_area_m2=round(f.area_m2, 2),
            gross_area_ha=round(f.area_m2 / 10_000.0, 4),
            soil_profile_id=field_soil[f.field_id],
            outlet_node_id=net.field_outlet[f.field_id],
            group=net.field_group[f.field_id],
            owner_ref=None,
            source_model_ids=f.source_model_ids,
            supersedes=[],
            evidence_ids=["ev:delineate", "ev:field-review", "asm:app-eff-existing"],
            existing_application_efficiency=ops.ASSUMPTIONS["asm:app-eff-existing"].value,
        )
        feats.append(
            {
                "type": "Feature",
                "id": f.field_id,
                "geometry": f.geometry_wgs84,
                "properties": rec.model_dump(mode="json"),
            }
        )
    write_json(P / "fields.geojson", {"type": "FeatureCollection", "features": feats})
    area_m2 = {f.field_id: f.area_m2 for f in fields}
    area_ha = {k: v / 10_000.0 for k, v in area_m2.items()}

    # --- roster, service, assets, interventions -------------------------------------
    roster = ops.build_roster(pilot_id, net, area_ha, warabandi=warabandi)
    write_json(
        P / "roster.json",
        {"seasons": {k: [w.model_dump(mode="json") for w in v] for k, v in roster.items()}},
    )
    svc = ops.build_service_reference(roster, net, net.edges, warabandi=warabandi)
    write_json(P / "service_reference.json", [s.model_dump(mode="json") for s in svc])
    ab = ops.build_assets(pilot_id, net, area_m2)
    write_json(P / "assets.json", [a.model_dump(mode="json") for a in ab.assets])
    nodes = {n.node_id: n for n in net.nodes}
    lengths = {e.edge_id: netmod.reach_length_m(e, nodes, crs) for e in net.edges}
    types, instances = ops.build_interventions(pilot_id, net, net.edges, area_m2, ab, lengths)
    write_json(
        P / "interventions.json",
        {
            "types": [t.model_dump(mode="json") for t in types],
            "instances": [i.model_dump(mode="json") for i in instances],
        },
    )
    assumptions = list(ops.ASSUMPTIONS.values())
    if warabandi == "selected_area":
        assumptions = [a for a in assumptions if a.evidence_id != "asm:watercourse-cca"]
    for a in assumptions:
        ev.append(
            _ev(
                evidence_id=a.evidence_id,
                source_title=a.title,
                kind=EvidenceKind.assumption,
                verification_state=VerificationState.unchecked,
                units=a.unit,
                transformation=f"declared value {a.value} {a.unit}",
                method_version=INGESTION_VERSION,
                assumption_range=AssumptionRange(low=a.low, high=a.high, unit=a.unit),
                limitations=[
                    a.basis,
                    "editable scenario assumption; no dated local quote or record",
                ],
                allowed_use="scenario input; label as assumed",
            )
        )
    ev.append(
        _ev(
            evidence_id="asm:existing-assets",
            source_title="Existing pond and shared tubewell",
            kind=EvidenceKind.assumption,
            verification_state=VerificationState.unchecked,
            transformation=f"existing pond on {ab.pond_field} sized to one 75 mm irrigation; shared "
            f"tubewell at the WC1 tail outlet serving {len(ab.pump_fields)} fields",
            limitations=[
                "explicitly assumed (PRD §6.4); not observed in imagery or records",
                (
                    "pond footprint lies inside the field's gross area and is already out of "
                    "baseline cropping (not subtracted again)"
                ),
            ],
        )
    )

    # --- resource status ------------------------------------------------------------
    write_json(P / "resource_status.json", resource_status(bundle_manifest, proc, now, len(fields)))

    # --- pilot.json -----------------------------------------------------------------
    evidence_ids = [e.evidence_id for e in ev]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("duplicate evidence ids")
    write_json(P / "evidence.json", [e.model_dump(mode="json") for e in ev])
    files_wo_pilot = sorted(
        (str(p.relative_to(P)), file_sha256(p)) for p in P.rglob("*") if p.is_file()
    )
    pilot = Pilot(
        pilot_id=pilot_id,
        pilot_version=pilot_version,
        name=name,
        geographic_name_basis=geographic_name_basis,
        aoi_geojson_ref="aoi.geojson",
        aoi_bbox=aoi.bbox,
        aoi_area_m2=round(aoi.area_m2, 2),
        metric_crs=aoi.metric_crs_id,
        state=PackageState.published,
        review_flags=ReviewFlags(
            geography_reviewed=True,
            topology_structurally_valid=True,
            rights_verification="assumed",
            cost_evidence="assumed",
            crop_calibration="uncalibrated",
        ),
        source_refs=sorted(e for e in evidence_ids if e.startswith("ev:")),
        imagery=imagery_refs,
        package_sha256=content_hash(files_wo_pilot),
        created_at=now,
        terrain_ref=terrain_ref,
        weather_index_ref="weather/index.json",
        bundle_ref=bundle_ref,
    )
    write_json(P / "pilot.json", pilot.model_dump(mode="json"))
    write_manifest(P, pilot_id, pilot_version, bundle_manifest, proc, now)
    return P


def write_manifest(
    P: Path, pilot_id: str, pilot_version: str, bundle_manifest: dict, proc: dict, now
) -> PilotManifest:
    files = []
    for p in sorted(P.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(P))
        if rel in MANIFEST_EXCLUDE:
            continue
        files.append(
            ManifestFile(
                path=rel, size_bytes=p.stat().st_size, sha256=file_sha256(p), kind=kind_of(rel)
            )
        )
    src_ids = sorted(
        {f"s2:{r['scene_id']}" for r in proc["imagery"]}
        | {
            f"weather:{proc['weather']['weather_series_id']}",
            f"delineate:{proc['inference']['inference_key']}",
            f"bundle:{bundle_manifest['pilot_id']}/{bundle_manifest['bundle_id']}",
        }
        | {f["id"] for f in read_json(P / "canals.geojson")["features"]}
    )
    m = PilotManifest(
        pilot_id=pilot_id,
        pilot_version=pilot_version,
        state=PackageState.published,
        files=files,
        source_ids=src_ids,
        licenses=sorted(
            {
                s2.LICENSE_ID,
                overpass.LICENSE_ID,
                grain.LICENSE_ID,
                openmeteo.LICENSE_ID,
                copdem.LICENSE_ID,
                "AGPL-3.0 (Delineate Anything code)",
            }
        ),
        processing_versions={
            "ingestion": INGESTION_VERSION,
            "package_format": PACKAGE_FORMAT_VERSION,
            "review_rules": REVIEW_RULES_VERSION,
            "display_stretch": STRETCH_ID,
            "network_template": netmod.NETWORK_TEMPLATE,
            "delineate_upstream_commit": delineate.UPSTREAM_COMMIT,
            "delineate_checkpoint": delineate.CHECKPOINT_ID,
        },
        generated_at=now,
    )
    write_json(P / "manifest.json", m.model_dump(mode="json"))
    return m


GATES = (
    "docs_checked",
    "asset_identified",
    "downloaded",
    "checksum_verified",
    "parsed",
    "geographically_reviewed",
    "runtime_validated",
)


def _gate(ok: bool | None, at, detail: str) -> dict:
    return {
        "result": "passed" if ok else ("not_applicable" if ok is None else "failed"),
        "at": iso(at) if isinstance(at, datetime) else at,
        "detail": detail,
    }


def resource_status(bm: dict, proc: dict, now: datetime, n_fields: int) -> dict:
    """T2.1 gates per resource, each with its own timestamp/result."""
    files = bm["files"]

    def first(kind):
        return next((f for f in files if f["kind"] == kind), None)

    st: dict[str, Any] = {}
    item = first("stac_item")
    st["sentinel2"] = {
        "docs_checked": _gate(
            True, item["retrieved_at"], "Earth Search STAC v1 collection sentinel-2-l2a"
        ),
        "asset_identified": _gate(
            True,
            item["retrieved_at"],
            "asset keys resolved from item metadata: "
            + ", ".join(sorted(proc["imagery"][0]["assets"])),
        ),
        "downloaded": _gate(
            True, item["retrieved_at"], "bounded COG windows (red, green, blue, nir, scl)"
        ),
        "checksum_verified": _gate(True, now, "bundle sha256 verified on import"),
        "parsed": _gate(True, now, "rasterio windows on native 10 m grid"),
        "geographically_reviewed": _gate(
            True,
            now,
            "AOI valid fraction "
            + ", ".join(f"{r['scene_id']}={r['aoi_valid_fraction']:.3f}" for r in proc["imagery"])
            + "; OSM canals overlaid on the display image (review_overlay.png); positional "
            "accuracy of the OSM lines not independently confirmed",
        ),
        "runtime_validated": _gate(True, now, "display image, NDVI and Delineate input generated"),
    }
    osm = first("osm_overpass")
    st["osm_overpass"] = {
        "docs_checked": _gate(
            True, osm["retrieved_at"], "Overpass API, waterway=canal|ditch|drain"
        ),
        "asset_identified": _gate(True, osm["retrieved_at"], "bounded bbox query text stored"),
        "downloaded": _gate(True, osm["retrieved_at"], f"{proc['canals']['osm_features']} ways"),
        "checksum_verified": _gate(True, now, f"sha256 {osm['sha256']}"),
        "parsed": _gate(True, now, "ids osm:way/<id>, tags preserved"),
        "geographically_reviewed": _gate(True, now, "overlaid on the Sentinel-2 display image"),
        "runtime_validated": _gate(True, now, "parent canal anchors the declared graph"),
    }
    g = first("grain_parquet")
    gs = bm["sources"].get("grain", {})
    if g:
        st["grain"] = {
            "docs_checked": _gate(True, g["retrieved_at"], "Zenodo record 16786488 listing read"),
            "asset_identified": _gate(True, g["retrieved_at"], gs.get("member", "")),
            "downloaded": _gate(
                True, g["retrieved_at"], "Pakistan GeoParquet member via HTTP range"
            ),
            "checksum_verified": _gate(
                True,
                g["retrieved_at"],
                f"member CRC-32 {gs.get('crc32')}; archive MD5 not verifiable from a partial read",
            ),
            "parsed": _gate(
                True, now, f"{proc['canals']['grain_features']} features in AOI window"
            ),
            "geographically_reviewed": _gate(
                proc["canals"]["grain_features"] > 0,
                now,
                "GRAIN features in the AOI window"
                if proc["canals"]["grain_features"]
                else "no GRAIN features inside the AOI window",
            ),
            "runtime_validated": _gate(None, now, "OSM features anchor the graph"),
        }
    else:
        st["grain"] = {k: _gate(False, now, gs.get("unavailable", "not acquired")) for k in GATES}
    wf = first("weather_raw")
    w = proc["weather"]
    st["open_meteo"] = {
        "docs_checked": _gate(
            True, wf["retrieved_at"], "historical archive API, timezone Asia/Karachi"
        ),
        "asset_identified": _gate(True, wf["retrieved_at"], f"model {w['source_model']}"),
        "downloaded": _gate(True, wf["retrieved_at"], f"{w['start']}..{w['end']}"),
        "checksum_verified": _gate(True, now, f"sha256 {w['source_sha256']}"),
        "parsed": _gate(True, now, f"{w['rows']} days, {len(w['complete_years'])} complete years"),
        "geographically_reviewed": _gate(True, now, f"returned grid point {w['point_returned']}"),
        "runtime_validated": _gate(True, now, "T2.5 asserts passed; no missing days"),
    }
    d = first("dem_window")
    if d and proc.get("terrain"):
        st["copernicus_dem"] = {
            "docs_checked": _gate(True, d["retrieved_at"], "AWS open data GLO-30 COG"),
            "asset_identified": _gate(True, d["retrieved_at"], d["source_url"]),
            "downloaded": _gate(True, d["retrieved_at"], "AOI window"),
            "checksum_verified": _gate(True, now, f"sha256 {d['sha256']}"),
            "parsed": _gate(
                True, now, f"{proc['terrain']['min_m']:.1f}-{proc['terrain']['max_m']:.1f} m"
            ),
            "geographically_reviewed": _gate(None, now, "display context only"),
            "runtime_validated": _gate(True, now, "Terrarium PNG encoded and round-trip tested"),
        }
    inf = proc["inference"]
    st["delineate_anything"] = {
        "docs_checked": _gate(True, now, f"upstream {inf['upstream_commit']} README/config guide"),
        "asset_identified": _gate(True, now, delineate.CHECKPOINT_ID),
        "downloaded": _gate(True, now, "weights in data/models/delineate-anything (SHA256SUMS)"),
        "checksum_verified": _gate(
            True,
            now,
            f"checkpoint sha256 {next(iter((inf.get('checkpoints') or {}).values()), '')}",
        ),
        "parsed": _gate(True, inf["finished_at"], f"{inf['raw_polygons']} raw polygons"),
        "geographically_reviewed": _gate(
            True, now, f"{n_fields} reviewed fields; overlay review_overlay.png"
        ),
        "runtime_validated": _gate(
            True,
            inf["finished_at"],
            f"{inf['device']} {inf['wall_seconds']} s; "
            "upstream sample run first (evidence/benchmarks)",
        ),
    }
    st["soil_prior"] = {
        "docs_checked": _gate(True, now, "AquaCrop predefined soil classes"),
        "asset_identified": _gate(True, now, "SiltLoam, Loam"),
        "downloaded": _gate(None, now, "built into AquaCrop"),
        "checksum_verified": _gate(None, now, "n/a"),
        "parsed": _gate(None, now, "validated by the science stream"),
        "geographically_reviewed": _gate(False, now, "no local soil survey or SoilGrids check"),
        "runtime_validated": _gate(None, now, "science stream"),
    }
    return {"generated_at": iso(now), "gates": list(GATES), "resources": st}


def _unused() -> None:  # keep imports referenced for type checkers
    _ = (math, Point, mapping, to_metric)
