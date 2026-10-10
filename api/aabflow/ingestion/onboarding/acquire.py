"""Online acquisition stage: real sources → immutable raw bundle (T2.1-T2.6).

Every source is fetched from its official endpoint, written once under
``data/raw/bundles/<pilot>/<bundle_id>/`` with its query/URL, retrieval time,
SHA-256 and license, and listed in ``bundle_manifest.json``. Processing never
touches the network; it reads only the bundle (``process.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..aoi import Aoi
from ..common import IngestionError, RawStore, iso, utc_now
from ..grain import reader as grain
from ..osm import overpass
from ..packages.bundle import BundleWriter, bundle_id_for
from ..stac import sentinel2 as s2
from ..terrain import copdem
from ..weather import openmeteo

Progress = Callable[[str, float | None, str], None]


def _noop(stage: str, frac: float | None, detail: str) -> None:
    pass


@dataclass(frozen=True)
class AcquisitionConfig:
    # Rabi wheat canopy is closed and parcels are distinct in Feb; Dec-Jan gives a
    # second, earlier crop-stage observation for NDVI context.
    primary_window: tuple[str, str] = ("2025-02-01", "2025-03-10")
    secondary_window: tuple[str, str] = ("2024-12-10", "2025-01-31")
    max_scene_cloud: float = 20.0
    min_aoi_valid_fraction: float = 0.95
    window_buffer_m: float = 600.0  # inference context around the AOI
    canal_buffer_deg: float = 0.01
    weather_start: date = date(2014, 1, 1)
    weather_end: date = date(2025, 12, 31)
    weather_model: str | None = "era5_seamless"
    dem: bool = True
    grain: bool = True


class Cancelled(IngestionError):
    pass


def _select_scene(
    aoi: Aoi, window: tuple[str, str], cfg: AcquisitionConfig, progress: Progress, label: str
) -> tuple[dict, list[dict], list[dict]]:
    items = s2.search_items(aoi, window[0], window[1], max_cloud=cfg.max_scene_cloud)
    if not items:
        raise IngestionError(f"no Sentinel-2 L2A items fully covering the AOI in {window}")
    screening = []
    for i, it in enumerate(items):
        progress(f"imagery:{label}:screen", i / len(items), it["id"])
        screening.append(s2.screen_scene(it, aoi))
    ok = [s for s in screening if s["aoi_valid_fraction"] >= cfg.min_aoi_valid_fraction]
    if not ok:
        best = max(screening, key=lambda s: s["aoi_valid_fraction"])
        raise IngestionError(
            f"no scene in {window} with AOI valid fraction ≥ {cfg.min_aoi_valid_fraction} "
            f"(best {best['scene_id']}: {best['aoi_valid_fraction']:.3f})"
        )
    # Highest AOI valid fraction, then lowest scene cloud, then latest date.
    ok.sort(key=lambda s: (-s["aoi_valid_fraction"], s["scene_cloud_cover"] or 0, s["datetime"]))
    chosen_id = ok[0]["scene_id"]
    item = next(it for it in items if it["id"] == chosen_id)
    return item, items, screening


def acquire_bundle(
    pilot_id: str,
    aoi: Aoi,
    data_dir: Path,
    cfg: AcquisitionConfig = AcquisitionConfig(),
    progress: Progress = _noop,
    should_cancel: Callable[[], bool] = lambda: False,
    name: str | None = None,
    geographic_name_basis: str | None = None,
) -> Path:
    """Fetch all sources for ``aoi`` into a new raw bundle; returns the bundle root."""
    aoi.check_limits()
    store = RawStore(Path(data_dir) / "raw")
    aoi_gj = aoi.feature_collection({"pilot_id": pilot_id, "name": name})
    started = utc_now()
    bw = BundleWriter(store, pilot_id, bundle_id_for(pilot_id, aoi_gj, started))
    bw.add_json("aoi.geojson", aoi_gj, "aoi")

    def check():
        if should_cancel():
            raise Cancelled("acquisition cancelled")

    # --- Sentinel-2 ------------------------------------------------------
    px = aoi.estimate_pixels(10.0, cfg.window_buffer_m)
    if px > s2_pixel_budget():
        raise IngestionError(f"window {px} px exceeds the per-scene pixel budget")
    scenes = []
    for label, window in (("primary", cfg.primary_window), ("secondary", cfg.secondary_window)):
        check()
        progress(f"imagery:{label}:search", None, f"{window[0]}..{window[1]}")
        item, items, screening = _select_scene(aoi, window, cfg, progress, label)
        sid = item["id"]
        bw.add_json(f"stac/search-{label}.json", {
            "endpoint": s2.EARTH_SEARCH, "collection": s2.COLLECTION,
            "intersects": aoi_gj["features"][0]["geometry"], "datetime": f"{window[0]}/{window[1]}",
            "query": {"eo:cloud_cover": {"lt": cfg.max_scene_cloud}},
            "retrieved_at": utc_now(), "item_ids": [it["id"] for it in items],
        }, "stac_search", source_url=s2.EARTH_SEARCH)  # fmt: skip
        bw.add_json(f"stac/screening-{label}.json", screening, "stac_screening")
        bw.add_json(f"stac/items/{sid}.json", item, "stac_item",
                    source_url=f"{s2.EARTH_SEARCH}/collections/{s2.COLLECTION}/items/{sid}",
                    retrieved_at=iso(utc_now()), license_id=s2.LICENSE_ID)  # fmt: skip
        progress(f"imagery:{label}:read", None, sid)
        sw = s2.read_scene(item, aoi, cfg.window_buffer_m)
        import tempfile  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as td:
            for band in ("red", "green", "blue", "nir", "scl"):
                arr = sw.scl if band == "scl" else sw.bands[band]
                ref = getattr(sw.assets, band)
                tp = s2.write_geotiff(Path(td) / f"{band}.tif", [arr], sw.grid, ref.nodata, [band])
                bw.add_file(f"sentinel2/{sid}/{band}.tif", tp, f"s2_window_{band}",
                            source_url=ref.href, retrieved_at=iso(utc_now()),
                            license_id=s2.LICENSE_ID,
                            note="original DN window on the scene's native 10 m grid"
                            + (" (SCL 20 m, nearest-neighbour)" if band == "scl" else ""))  # fmt: skip
        bw.add_json(f"sentinel2/{sid}/window.json", {
            "scene_id": sid, "label": label, "grid_crs": sw.grid.crs,
            "grid_transform": list(sw.grid.transform)[:6], "width": sw.grid.width,
            "height": sw.grid.height, "bounds": sw.grid.bounds, "buffer_m": cfg.window_buffer_m,
            "assets": sw.assets.as_dict(), "read": sw.read_meta,
        }, "s2_window_meta")  # fmt: skip
        scenes.append({"label": label, "scene_id": sid})
    bw.sources["sentinel2"] = scenes

    # --- canals: OSM Overpass (fast path) and GRAIN subset -----------------
    check()
    w, s, e, n = aoi.bbox
    b = cfg.canal_buffer_deg
    q = overpass.build_query((w - b, s - b, e + b, n + b))
    progress("canals:overpass", None, "bounded Overpass query")
    res = overpass.fetch(q)
    bw.add_bytes("osm/overpass_query.txt", q.encode(), "osm_query", source_url=overpass.OVERPASS_URL)
    bw.add_bytes("osm/overpass.json", res.content, "osm_overpass", source_url=res.url,
                 retrieved_at=iso(res.retrieved_at), license_id=overpass.LICENSE_ID)  # fmt: skip
    bw.sources["osm"] = {"endpoint": overpass.OVERPASS_URL, "retrieved_at": iso(res.retrieved_at)}
    if cfg.grain:
        check()
        progress("canals:grain", None, "GRAIN Pakistan GeoParquet member (HTTP range)")
        mf = grain.fetch_member()
        bw.add_bytes("grain/pakistan_GRAIN_v.1.0.parquet", mf.content, "grain_parquet",
                     source_url=grain.ZIP_URL, retrieved_at=iso(utc_now()),
                     license_id=grain.LICENSE_ID,
                     note=f"zip member {mf.member}; CRC-32 {mf.crc32} verified on extraction")  # fmt: skip
        bw.sources["grain"] = {
            "record": grain.ZENODO_RECORD_API, "member": mf.member, "crc32": mf.crc32,
            "archive_size": mf.archive_size, "member_size": mf.file_size,
            "range_requests": mf.range_requests, "pakistan_entries": mf.listing,
            "archive_md5_verified": False,
            "archive_md5_note": "archive MD5 not verifiable from a partial (range) read",
        }  # fmt: skip

    # --- weather -----------------------------------------------------------
    check()
    lon, lat = aoi.centroid
    progress("weather:open-meteo", None, f"{lat:.4f},{lon:.4f}")
    wr = openmeteo.request_archive(lat, lon, cfg.weather_start, cfg.weather_end, cfg.weather_model)
    bw.add_bytes("weather/open-meteo-archive.json", wr.content, "weather_raw", source_url=wr.url,
                 retrieved_at=iso(wr.retrieved_at), license_id=openmeteo.LICENSE_ID)  # fmt: skip
    bw.sources["weather"] = {
        "endpoint": openmeteo.ARCHIVE_URL,
        "params": openmeteo.request_params(lat, lon, cfg.weather_start, cfg.weather_end, cfg.weather_model),
        "retrieved_at": iso(wr.retrieved_at),
    }

    # --- terrain (optional) -----------------------------------------------
    if cfg.dem:
        check()
        progress("terrain:copdem", None, copdem.tile_url(lat, lon))
        try:
            import tempfile  # noqa: PLC0415

            import rasterio  # noqa: PLC0415

            h, tf, crs, url = copdem.read_dem_window(aoi.bbox)
            with tempfile.TemporaryDirectory() as td:
                tp = Path(td) / "dem.tif"
                with rasterio.open(tp, "w", driver="GTiff", width=h.shape[1], height=h.shape[0],
                                   count=1, dtype="float32", crs=crs, transform=tf,
                                   compress="deflate") as dst:  # fmt: skip
                    dst.write(h, 1)
                bw.add_file("terrain/copdem_glo30_window.tif", tp, "dem_window", source_url=url,
                            retrieved_at=iso(utc_now()), license_id=copdem.LICENSE_ID,
                            note="Copernicus DEM GLO-30 original heights (m) for the AOI window")  # fmt: skip
            bw.sources["terrain"] = {"source_url": url}
        except IngestionError as exc:
            bw.sources["terrain"] = {"unavailable": str(exc)}

    root = bw.finalize(
        aoi_gj,
        {
            "name": name,
            "geographic_name_basis": geographic_name_basis,
            "acquisition_config": {k: str(v) for k, v in vars(cfg).items()},
            "acquired_started_at": started,
        },
    )
    progress("acquired_raw", 1.0, str(root.parent))
    return root.parent


def s2_pixel_budget() -> int:
    from ..aoi import MAX_SCENE_PIXELS  # noqa: PLC0415

    return MAX_SCENE_PIXELS
