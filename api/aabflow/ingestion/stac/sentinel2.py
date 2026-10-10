"""Sentinel-2 L2A acquisition from Earth Search STAC (T2.1, T2.4).

* Search by AOI/date with a scene-level cloud filter (first filter only).
* Discover asset keys from item metadata (``eo:bands`` common names, roles,
  media type); never hard-code them.
* Read bounded COG windows; keep CRS, transform, nodata, scale/offset and
  original DN pixels. Masks are resampled with nearest neighbour.
* Compute the valid fraction inside the AOI from SCL semantics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from rasterio.windows import Window, from_bounds
from shapely.geometry import mapping, shape

from ..aoi import Aoi
from ..common import IngestionError

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
LICENSE = "proprietary: Copernicus Sentinel data terms (free, full and open)"
LICENSE_ID = "copernicus-sentinel-data-terms"

# Scene Classification Layer (Sen2Cor L2A product spec): classes treated as invalid.
SCL_CLASSES = {
    0: "no_data",
    1: "saturated_or_defective",
    2: "dark_area_pixels",
    3: "cloud_shadows",
    4: "vegetation",
    5: "not_vegetated",
    6: "water",
    7: "unclassified",
    8: "cloud_medium_probability",
    9: "cloud_high_probability",
    10: "thin_cirrus",
    11: "snow_ice",
}
SCL_INVALID = frozenset({0, 1, 3, 8, 9, 10, 11})

GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "2",
    "AWS_NO_SIGN_REQUEST": "YES",
    "VSI_CACHE": "TRUE",
}

_COG = "cloud-optimized"


@dataclass
class AssetRef:
    key: str
    href: str
    gsd: float | None
    scale: float
    offset: float
    nodata: float | None
    dtype: str | None


@dataclass
class SceneAssets:
    red: AssetRef
    green: AssetRef
    blue: AssetRef
    nir: AssetRef
    scl: AssetRef

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {k: vars(getattr(self, k)) for k in ("red", "green", "blue", "nir", "scl")}


def _raster_band_meta(asset: dict) -> dict:
    bands = asset.get("raster:bands") or [{}]
    return bands[0] if bands else {}


def _common_names(asset: dict) -> set[str]:
    out = set()
    for b in asset.get("eo:bands") or []:
        if b.get("common_name"):
            out.add(b["common_name"])
    return out


def resolve_assets(item: dict) -> SceneAssets:
    """Choose RGB/NIR/SCL COG assets from the item's own metadata.

    Preference: assets whose media type is a cloud-optimized GeoTIFF; band identity
    from ``eo:bands[].common_name`` when present, else from the asset key; NIR is
    the 10 m ``nir`` (B08), never the 20 m narrow ``nir08`` (B8A).
    """
    assets: dict[str, dict] = item["assets"]
    cogs = {k: a for k, a in assets.items() if _COG in (a.get("type") or "")}
    if not cogs:
        raise IngestionError(f"{item.get('id')}: no cloud-optimized GeoTIFF assets")

    def pick(name: str, gsd: float | None) -> AssetRef:
        cands = []
        for k, a in cogs.items():
            names = _common_names(a)
            if name in names or k == name:
                meta = _raster_band_meta(a)
                g = a.get("gsd", meta.get("spatial_resolution"))
                if gsd is not None and g is not None and float(g) != gsd:
                    continue
                cands.append((k, a, meta, g))
        if not cands:
            raise IngestionError(f"{item.get('id')}: no COG asset for band {name!r}")
        cands.sort(key=lambda c: (c[0] != name, c[0]))
        k, a, meta, g = cands[0]
        return AssetRef(
            key=k,
            href=a["href"],
            gsd=float(g) if g is not None else None,
            scale=float(meta.get("scale", 1.0)),
            offset=float(meta.get("offset", 0.0)),
            nodata=meta.get("nodata"),
            dtype=meta.get("data_type"),
        )

    scl_key = next((k for k in cogs if k.lower() == "scl"), None)
    if scl_key is None:
        scl_key = next(
            (k for k, a in cogs.items() if "scl" in (a.get("title") or "").lower()), None
        )
    if scl_key is None:
        raise IngestionError(f"{item.get('id')}: no SCL classification asset")
    scl_meta = _raster_band_meta(cogs[scl_key])
    scl = AssetRef(
        key=scl_key,
        href=cogs[scl_key]["href"],
        gsd=float(cogs[scl_key].get("gsd", scl_meta.get("spatial_resolution", 20))),
        scale=1.0,
        offset=0.0,
        nodata=scl_meta.get("nodata"),
        dtype=scl_meta.get("data_type"),
    )
    return SceneAssets(
        red=pick("red", 10.0),
        green=pick("green", 10.0),
        blue=pick("blue", 10.0),
        nir=pick("nir", 10.0),
        scl=scl,
    )


def search_items(
    aoi: Aoi,
    start: str,
    end: str,
    max_cloud: float = 20.0,
    url: str = EARTH_SEARCH,
    collection: str = COLLECTION,
) -> list[dict]:
    """STAC search; returns raw item dicts whose footprint fully contains the AOI."""
    from pystac_client import Client

    client = Client.open(url)
    search = client.search(
        collections=[collection],
        intersects=mapping(aoi.geometry),
        datetime=f"{start}/{end}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        max_items=500,
    )
    items = [it.to_dict() for it in search.items()]
    full = [it for it in items if shape(it["geometry"]).contains(aoi.geometry)]
    full.sort(key=lambda it: it["properties"]["datetime"])
    return full


@dataclass
class Window10m:
    crs: str
    transform: rasterio.Affine
    width: int
    height: int
    bounds: tuple[float, float, float, float]


def grid_for(aoi: Aoi, scene_crs: str, buffer_m: float, res: float = 10.0) -> Window10m:
    """Pixel-aligned 10 m window covering the buffered AOI in the scene CRS."""
    g = shape(transform_geom("EPSG:4326", scene_crs, mapping(aoi.geometry)))
    minx, miny, maxx, maxy = g.buffer(buffer_m).bounds
    # Snap to the Sentinel-2 10 m grid (tile origins are multiples of 10 m).
    minx = math.floor(minx / res) * res
    miny = math.floor(miny / res) * res
    maxx = math.ceil(maxx / res) * res
    maxy = math.ceil(maxy / res) * res
    w = round((maxx - minx) / res)
    h = round((maxy - miny) / res)
    return Window10m(
        crs=scene_crs,
        transform=rasterio.Affine(res, 0, minx, 0, -res, maxy),
        width=w,
        height=h,
        bounds=(minx, miny, maxx, maxy),
    )


def read_window(href: str, grid: Window10m, categorical: bool) -> tuple[np.ndarray, dict]:
    """Read a bounded window of one COG onto the 10 m grid.

    10 m bands are read at native resolution (pixel-aligned, no resampling).
    Coarser categorical masks (SCL, 20 m) use nearest-neighbour onto the grid.
    """
    with rasterio.Env(**GDAL_ENV), rasterio.open(href) as src:
        if str(src.crs) != grid.crs and src.crs.to_string() != grid.crs:
            raise IngestionError(f"{href}: CRS {src.crs} != expected {grid.crs}")
        win: Window = from_bounds(*grid.bounds, transform=src.transform)
        native = abs(src.transform.a)
        # Masks: nearest neighbour; 10 m bands are pixel-aligned so no resampling occurs.
        resampling = Resampling.nearest
        if not categorical and abs(native - abs(grid.transform.a)) > 1e-6:
            raise IngestionError(f"{href}: expected 10 m band, got {native} m")
        data = src.read(
            1,
            window=win,
            out_shape=(grid.height, grid.width),
            resampling=resampling,
            boundless=True,
            fill_value=src.nodata if src.nodata is not None else 0,
        )
        meta = {
            "source_crs": src.crs.to_string(),
            "source_transform": list(src.transform)[:6],
            "source_resolution_m": native,
            "source_nodata": src.nodata,
            "source_dtype": src.dtypes[0],
            "window": {
                "col_off": float(win.col_off),
                "row_off": float(win.row_off),
                "width": float(win.width),
                "height": float(win.height),
            },
            "resampling": "nearest (categorical)" if categorical else "none (native 10 m)",
        }
    return data, meta


def aoi_mask(aoi: Aoi, grid: Window10m) -> np.ndarray:
    """True where the pixel centre is inside the AOI."""
    g = transform_geom("EPSG:4326", grid.crs, mapping(aoi.geometry))
    return geometry_mask(
        [g], out_shape=(grid.height, grid.width), transform=grid.transform, invert=True
    )


def valid_mask_from_scl(scl: np.ndarray, invalid: frozenset[int] = SCL_INVALID) -> np.ndarray:
    return ~np.isin(scl, list(invalid))


def aoi_valid_fraction(scl: np.ndarray, inside: np.ndarray) -> float:
    if inside.sum() == 0:
        raise IngestionError("AOI mask covers no pixels of the window")
    return float(valid_mask_from_scl(scl)[inside].mean())


def scl_histogram(scl: np.ndarray, inside: np.ndarray) -> dict[str, int]:
    vals, counts = np.unique(scl[inside], return_counts=True)
    return {
        SCL_CLASSES.get(int(v), f"class_{int(v)}"): int(c)
        for v, c in zip(vals, counts, strict=True)
    }


def to_reflectance(dn: np.ndarray, ref: AssetRef) -> np.ndarray:
    """Physical surface reflectance via the item's published scale/offset."""
    out = dn.astype("float64") * ref.scale + ref.offset
    if ref.nodata is not None:
        out[dn == ref.nodata] = np.nan
    return out


def offset_consistency(
    bands_dn: dict[str, np.ndarray],
    refs: dict[str, AssetRef],
    valid: np.ndarray,
    tolerance: float = 0.01,
) -> dict:
    """Check the published BOA offset against the pixel data before applying it.

    For processing baseline ≥04.00 L2A DNs carry a +1000 offset that the STAC
    ``raster:bands.offset`` (-0.1) removes. If applying the offset would make more
    than ``tolerance`` of valid pixels clearly negative (< -0.01), the DNs are already
    offset-free and the published offset contradicts the data; it is then not applied
    and the decision is recorded.
    """
    neg = {}
    for name, dn in bands_dn.items():
        ref = refs[name]
        v = dn[valid & (dn != (ref.nodata if ref.nodata is not None else -1))]
        if v.size == 0:
            continue
        refl = v.astype("float64") * ref.scale + ref.offset
        neg[name] = float((refl < -0.01).mean())
    apply = all(f <= tolerance for f in neg.values())
    return {
        "published_offsets": {n: refs[n].offset for n in bands_dn},
        "negative_fraction_if_applied": neg,
        "offset_applied": apply,
        "decision": "published offset applied"
        if apply
        else "published offset NOT applied: it would make valid pixels negative, so DNs "
        "are treated as offset-free (scale only)",
    }


def with_offset(ref: AssetRef, apply_offset: bool) -> AssetRef:
    return ref if apply_offset else AssetRef(**{**vars(ref), "offset": 0.0})


def ndvi(red_refl: np.ndarray, nir_refl: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """(NIR-red)/(NIR+red) on physical reflectance; NaN where invalid or denominator<=0."""
    den = nir_refl + red_refl
    out = np.full(red_refl.shape, np.nan, dtype="float64")
    ok = valid & np.isfinite(den) & (den > 1e-6)
    out[ok] = (nir_refl[ok] - red_refl[ok]) / den[ok]
    return out


@dataclass
class SceneWindow:
    item: dict
    assets: SceneAssets
    grid: Window10m
    bands: dict[str, np.ndarray]  # original DN on the 10 m grid
    scl: np.ndarray
    read_meta: dict[str, dict] = field(default_factory=dict)

    @property
    def scene_id(self) -> str:
        return self.item["id"]

    @property
    def acquired_at(self) -> datetime:
        return datetime.fromisoformat(self.item["properties"]["datetime"])


def scene_crs(item: dict) -> str:
    p = item["properties"]
    code = p.get("proj:code") or (f"EPSG:{p['proj:epsg']}" if p.get("proj:epsg") else None)
    if not code:
        raise IngestionError(f"{item['id']}: item has no proj:code/proj:epsg")
    return code


def screen_scene(item: dict, aoi: Aoi, buffer_m: float = 0.0) -> dict[str, Any]:
    """Cheap AOI-level screening: read only SCL and compute the AOI valid fraction."""
    assets = resolve_assets(item)
    grid = grid_for(aoi, scene_crs(item), buffer_m)
    scl, _ = read_window(assets.scl.href, grid, categorical=True)
    inside = aoi_mask(aoi, grid)
    return {
        "scene_id": item["id"],
        "datetime": item["properties"]["datetime"],
        "scene_cloud_cover": item["properties"].get("eo:cloud_cover"),
        "aoi_valid_fraction": aoi_valid_fraction(scl, inside),
        "scl_histogram": scl_histogram(scl, inside),
    }


def read_scene(item: dict, aoi: Aoi, buffer_m: float) -> SceneWindow:
    assets = resolve_assets(item)
    grid = grid_for(aoi, scene_crs(item), buffer_m)
    from concurrent.futures import ThreadPoolExecutor

    names = ("red", "green", "blue", "nir", "scl")
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {n: ex.submit(read_window, getattr(assets, n).href, grid, n == "scl") for n in names}
        results = {n: f.result() for n, f in futs.items()}
    bands = {n: results[n][0] for n in names[:4]}
    meta = {n: results[n][1] for n in names}
    scl = results["scl"][0]
    return SceneWindow(item=item, assets=assets, grid=grid, bands=bands, scl=scl, read_meta=meta)


def write_geotiff(path, arrays: list[np.ndarray], grid: Window10m, nodata, descriptions: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "count": len(arrays),
        "dtype": arrays[0].dtype.name,
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": nodata,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    if grid.width < 256 or grid.height < 256:
        profile.pop("blockxsize")
        profile.pop("blockysize")
        profile["tiled"] = False
    with rasterio.open(path, "w", **profile) as dst:
        for i, (a, d) in enumerate(zip(arrays, descriptions, strict=True), start=1):
            dst.write(a, i)
            dst.set_band_description(i, d)
    return path
