"""Processing stage: validated raw bundle → processed sources + raw inference (T2.4-T2.6).

Reads only the bundle (no network). Produces in ``<workdir>/processed/``:

* ``imagery/<scene>.webp|.json`` display images with corners and stretch,
  ``imagery/<scene>.ndvi.tif`` NDVI on physical reflectance with SCL mask,
  ``imagery/delineate_input.tif`` (primary scene, original DN, R/G/B order);
* ``canals.geojson`` observed OSM (+ GRAIN subset) features with provider ids/tags;
* ``weather/<series>.json|.parquet`` validated complete daily series;
* ``terrain/dem.png|.json`` Terrarium DEM (optional);
* ``fields_raw.geojson`` + ``fields_raw.gpkg`` untouched Delineate output.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from shapely.geometry import shape

from aabflow.domain.hashes import file_sha256, sha256_hex

from ..aoi import Aoi, to_metric
from ..common import IngestionError, dumps, iso, read_json, utc_now, write_json
from ..grain import reader as grain
from ..imagery import delineate
from ..imagery.display import render_display
from ..osm import overpass
from ..packages.bundle import Bundle
from ..stac import sentinel2 as s2
from ..terrain import copdem
from ..weather import openmeteo

MIN_WEATHER_YEARS = 10


@dataclass
class ProcessResult:
    imagery: list[dict] = field(default_factory=list)
    canals: dict[str, Any] = field(default_factory=dict)
    weather: dict[str, Any] = field(default_factory=dict)
    terrain: dict[str, Any] | None = None
    inference: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    cache_hits: list[str] = field(default_factory=list)


def _local_grid(path: Path) -> s2.Window10m:
    with rasterio.open(path) as src:
        b = src.bounds
        return s2.Window10m(
            crs=src.crs.to_string(),
            transform=src.transform,
            width=src.width,
            height=src.height,
            bounds=(b.left, b.bottom, b.right, b.top),
        )


def _read_local(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


def process_imagery(bundle: Bundle, aoi: Aoi, out: Path, res: ProcessResult) -> Path:
    """Display images, NDVI and the Delineate input for each bundled scene."""
    img_dir = out / "imagery"
    img_dir.mkdir(parents=True, exist_ok=True)
    primary_input = None
    for meta_f in bundle.files_of("s2_window_meta"):
        meta = bundle.read_json(meta_f["path"])
        sid = meta["scene_id"]
        item = bundle.read_json(f"stac/items/{sid}.json")
        assets = s2.resolve_assets(item)  # re-derived from the bundled item metadata
        base = f"sentinel2/{sid}"
        grid = _local_grid(bundle.path(f"{base}/red.tif"))
        bands = {
            b: _read_local(bundle.path(f"{base}/{b}.tif")) for b in ("red", "green", "blue", "nir")
        }
        scl = _read_local(bundle.path(f"{base}/scl.tif"))
        for b, arr in bands.items():
            if arr.shape != scl.shape:
                raise IngestionError(f"{sid}: band {b} grid differs from SCL grid")
        inside = s2.aoi_mask(aoi, grid)
        valid = s2.valid_mask_from_scl(scl)
        vf = s2.aoi_valid_fraction(scl, inside)
        refs = {b: getattr(assets, b) for b in bands}
        oc = s2.offset_consistency(bands, refs, valid)
        if not oc["offset_applied"]:
            res.warnings.append(f"{sid}: {oc['decision']}")
        refl = {
            b: s2.to_reflectance(bands[b], s2.with_offset(refs[b], oc["offset_applied"]))
            for b in bands
        }
        rgb = np.stack([refl["red"], refl["green"], refl["blue"]])
        disp = render_display(rgb, valid, grid.crs, grid.transform)
        (img_dir / f"{sid}.webp").write_bytes(disp.webp)
        nd = s2.ndvi(refl["red"], refl["nir"], valid)
        s2.write_geotiff(
            img_dir / f"{sid}.ndvi.tif", [nd.astype("float32")], grid, np.nan, ["ndvi"]
        )
        acquired = item["properties"]["datetime"]
        rec = {
            "scene_id": sid,
            "label": meta["label"],
            "collection": item.get("collection", s2.COLLECTION),
            "acquired_at": acquired,
            "image_ref": f"imagery/{sid}.webp",
            "corners_wgs84": disp.corners_wgs84,
            "bounds_wgs84": disp.bounds_wgs84,
            "width": disp.width,
            "height": disp.height,
            "display_crs": "EPSG:3857",
            "resolution_m": 10.0,
            "source_grid": {
                "crs": grid.crs,
                "transform": list(grid.transform)[:6],
                "width": grid.width,
                "height": grid.height,
            },
            "aoi_valid_fraction": round(vf, 6),
            "scene_cloud_cover": item["properties"].get("eo:cloud_cover"),
            "scl_histogram_aoi": s2.scl_histogram(scl, inside),
            "scl_invalid_classes": sorted(s2.SCL_INVALID),
            "assets": assets.as_dict(),
            "stretch": disp.stretch,
            "reflectance_offset_check": oc,
            "ndvi": {
                "ref": f"imagery/{sid}.ndvi.tif",
                "method": "(NIR-red)/(NIR+red) on surface reflectance (scale/offset from STAC); "
                "SCL-invalid pixels and NIR+red<=0 are NaN",
                "aoi_mean": float(np.nanmean(nd[inside]))
                if np.isfinite(nd[inside]).any()
                else None,
                "aoi_median": float(np.nanmedian(nd[inside]))
                if np.isfinite(nd[inside]).any()
                else None,
                "aoi_valid_fraction": round(float(np.isfinite(nd[inside]).mean()), 6),
                "interpretation": "observation context only; not water stress, crop identity "
                "or yield",
            },
            "item_sha256": file_sha256(bundle.path(f"stac/items/{sid}.json")),
            "window_sha256": {
                b: file_sha256(bundle.path(f"{base}/{b}.tif"))
                for b in ("red", "green", "blue", "nir", "scl")
            },
        }
        write_json(img_dir / f"{sid}.json", rec)
        res.imagery.append(rec)
        if meta["label"] == "primary":
            primary_input = s2.write_geotiff(
                img_dir / "delineate_input.tif",
                [bands["red"], bands["green"], bands["blue"]],
                grid,
                0,
                ["red (B04 DN)", "green (B03 DN)", "blue (B02 DN)"],
            )
    if primary_input is None:
        raise IngestionError("bundle has no primary Sentinel-2 scene")
    res.imagery.sort(key=lambda r: (r["label"] != "primary", r["acquired_at"]))
    return primary_input


def _jsonable(v):
    """Provider attribute → JSON value; naive provider timestamps stay as written."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return v


def process_canals(bundle: Bundle, aoi: Aoi, out: Path, res: ProcessResult) -> dict:
    payload = read_json(bundle.path("osm/overpass.json"))
    query = bundle.path("osm/overpass_query.txt").read_text()
    osm_meta = bundle.one("osm_overpass")
    feats = overpass.to_features(payload)
    osm_base = (payload.get("osm3s") or {}).get("timestamp_osm_base")
    grain_feats: list[dict] = []
    grain_info: dict[str, Any] = {"used": False}
    gf = bundle.files_of("grain_parquet")
    if gf:
        gdf = grain.read_subset(bundle.path(gf[0]["path"]), aoi.geometry.buffer(0.01).bounds)
        schema = grain.schema_summary(gdf)
        grain_info = {"used": True, "rows_in_window": len(gdf), "schema": schema}
        if len(gdf):
            idc = grain.id_column(gdf)
            for _, row in gdf.iterrows():
                sid = f"grain:{row[idc]}"
                props = {
                    k: (v.item() if hasattr(v, "item") else v)
                    for k, v in row.drop(labels=gdf.geometry.name).items()
                }
                props = {k: _jsonable(v) for k, v in props.items()}
                grain_feats.append(
                    {
                        "type": "Feature",
                        "id": sid,
                        "geometry": row.geometry.__geo_interface__,
                        "properties": {
                            "source_feature_id": sid,
                            "provider": "grain",
                            "observed": True,
                            "license": grain.LICENSE_ID,
                            "attributes": props,
                        },
                    }
                )
    else:
        res.warnings.append("GRAIN unavailable in bundle; OSM fallback used (T2.1)")
    fc = overpass.feature_collection(
        feats + grain_feats, query, osm_meta.get("retrieved_at"), osm_base
    )
    fc["properties"]["grain"] = grain_info
    write_json(out / "canals.geojson", fc)
    res.canals = {
        "ref": "canals.geojson",
        "osm_features": len(feats),
        "grain_features": len(grain_feats),
        "osm_base_timestamp": osm_base,
    }
    return fc


def choose_parent_canal(fc: dict, aoi: Aoi, preferred: str | None = None) -> dict:
    """Proposed parent canal: the preferred id if present, else the waterway=canal
    feature with the most length inside the AOI (a reviewable proposal, not topology)."""
    canals = [
        f
        for f in fc["features"]
        if f["properties"].get("provider") == "osm" and f["properties"].get("waterway") == "canal"
    ]
    if preferred:
        for f in canals:
            if f["id"] == preferred:
                return f
        raise IngestionError(f"preferred parent canal {preferred} not in the canal import")
    aoi_m = aoi.metric_geometry
    scored = []
    for f in canals:
        g = to_metric(shape(f["geometry"]), aoi.metric_crs)
        scored.append((g.intersection(aoi_m).length, f["id"], f))
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        raise IngestionError("no mapped waterway=canal crosses the AOI; cannot anchor the graph")
    scored.sort(key=lambda s: (-s[0], s[1]))
    return scored[0][2]


def process_weather(bundle: Bundle, out: Path, res: ProcessResult) -> dict:
    f = bundle.one("weather_raw")
    raw_path = bundle.path(f["path"])
    content = raw_path.read_bytes()
    payload = openmeteo.load_raw(content)
    params = bundle.manifest["sources"]["weather"]["params"]
    from datetime import date

    start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
    w = openmeteo.normalize_archive(payload)
    openmeteo.validate(w, start, end)
    years = openmeteo.complete_years(w)
    if len(years) < MIN_WEATHER_YEARS:
        raise IngestionError(
            f"only {len(years)} complete weather years; ≥{MIN_WEATHER_YEARS} required"
        )
    pt = openmeteo.returned_point(payload)
    sid = openmeteo.series_id_for(pt, start, end)
    wd = out / "weather"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / f"{sid}.json").write_bytes(content)
    pq = openmeteo.to_parquet_bytes(w)
    (wd / f"{sid}.parquet").write_bytes(pq)
    res.weather = {
        "weather_series_id": sid,
        "point_requested": (float(params["latitude"]), float(params["longitude"])),
        "point_returned": (pt.lat, pt.lon),
        "elevation_m": pt.elevation_m,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "complete_years": years,
        "source_model": params.get("models"),
        "raw_ref": f"weather/{sid}.json",
        "normalized_ref": f"weather/{sid}.parquet",
        "source_sha256": sha256_hex(content),
        "normalized_sha256": sha256_hex(pq),
        "retrieved_at": f.get("retrieved_at"),
        "source_url": f.get("source_url"),
        "units": {c: u for c, u in [(v[0], v[1]) for v in openmeteo.VARIABLES.values()]},
        "timezone": payload.get("timezone"),
        "generationtime_ms": payload.get("generationtime_ms"),
        "rows": len(w),
    }
    return res.weather


def process_terrain(bundle: Bundle, out: Path, res: ProcessResult) -> None:
    fs = bundle.files_of("dem_window")
    if not fs:
        res.warnings.append("terrain unavailable (optional)")
        return
    p = bundle.path(fs[0]["path"])
    with rasterio.open(p) as src:
        h = src.read(1)
        dem = copdem.encode_dem(h, src.transform, src.crs.to_string(), fs[0]["source_url"])
    td = out / "terrain"
    td.mkdir(parents=True, exist_ok=True)
    (td / "dem.png").write_bytes(dem.png)
    res.terrain = {
        "image_ref": "terrain/dem.png",
        "bounds": dem.bounds,
        "width": dem.width,
        "height": dem.height,
        "min_m": dem.min_m,
        "max_m": dem.max_m,
        "encoding": "terrarium",
        "decode": "height_m = (R*256 + G + B/256) - 32768",
        "crs": "EPSG:4326",
        "source_url": dem.source_url,
        "source_sha256": fs[0]["sha256"],
        "resolution_deg": dem.resolution_deg,
        "note": "Display context only; slope does not verify canal flow direction.",
    }
    write_json(td / "dem.json", res.terrain)


def run_inference(
    input_tif: Path,
    repo_root: Path,
    out: Path,
    res: ProcessResult,
    *,
    cache_only: bool = False,
) -> bool:
    """Prepare, run-or-reuse and collect Delineate. Returns False if still pending.

    ``cache_only`` reuses a completed run record and never starts the vision
    container. A miss stays ``pending`` with ``cache_hit`` false and no device.
    """
    job = delineate.prepare(input_tif, repo_root)
    res.inference = {
        "inference_key": job.key,
        "batch": str(job.batch_yaml.relative_to(repo_root)),
        "command": job.command_str(),
        "cache_hit": False,
        "device": None,
    }
    if cache_only and not job.done():
        res.inference["state"] = "pending"
        res.blockers.append(
            "inference_pending: no cached Delineate run for this input; "
            f"a new vision run was not started. Command not executed: {job.command_str()}"
        )
        return False
    try:
        rec = delineate.run(job)
    except delineate.InferencePending as p:
        res.inference["state"] = "pending"
        res.inference["cache_hit"] = False
        res.inference["device"] = None
        res.blockers.append(f"inference_pending: {p.command}")
        return False
    if rec.get("cache_hit"):
        res.cache_hits.append(f"delineate:{job.key}")
    raw = delineate.collect(job)
    write_json(out / "fields_raw.geojson", raw)
    shutil.copyfile(job.output_gpkg, out / "fields_raw.gpkg")
    res.inference.update(
        {
            "state": "done",
            "run_record": str(job.record.relative_to(repo_root)),
            "wall_seconds": rec.get("wall_seconds"),
            "device": rec.get("device"),
            "raw_polygons": len(raw["features"]),
            "gpkg_sha256": raw["properties"]["gpkg_sha256"],
            "input_sha256": file_sha256(input_tif),
            "checkpoints": rec.get("checkpoints"),
            "upstream_commit": rec.get("upstream_commit"),
            "base_config": rec.get("base_config_path"),
            "base_config_sha256": rec.get("base_config_sha256"),
            "started_at": rec.get("started_at"),
            "finished_at": rec.get("finished_at"),
            "cache_hit": bool(rec.get("cache_hit")),
        }
    )
    return True


def process_bundle(
    bundle: Bundle, out: Path, repo_root: Path, progress=None, *, cache_only: bool = False
) -> ProcessResult:
    progress = progress or (lambda *a: None)
    out.mkdir(parents=True, exist_ok=True)
    aoi = Aoi.from_geojson(bundle.read_json("aoi.geojson"))
    res = ProcessResult()
    progress("process:imagery", 0.1, "display, NDVI, Delineate input")
    input_tif = process_imagery(bundle, aoi, out, res)
    progress("process:canals", 0.3, "OSM/GRAIN canal features")
    process_canals(bundle, aoi, out, res)
    progress("process:weather", 0.4, "Open-Meteo normalization + validation")
    process_weather(bundle, out, res)
    progress("process:terrain", 0.5, "Copernicus DEM")
    process_terrain(bundle, out, res)
    progress("process:inference", 0.6, "Delineate Anything (cached run or pending)")
    run_inference(input_tif, repo_root, out, res, cache_only=cache_only)
    write_json(out / "process_result.json", {**vars(res), "processed_at": iso(utc_now())})
    return res


__all__ = ["ProcessResult", "choose_parent_canal", "dumps", "process_bundle"]
