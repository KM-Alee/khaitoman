"""Optional local terrain from Copernicus DEM GLO-30 (AWS open data COGs).

Produces a Terrarium-encoded PNG on an EPSG:4326 north-up grid plus bounds, for
MapLibre ``raster-dem`` (encoding "terrarium"):
``height_m = (R * 256 + G + B / 256) - 32768``.
Terrain is display context only; it does not verify flow direction (T4.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

from ..common import IngestionError
from ..stac.sentinel2 import GDAL_ENV

BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
LICENSE_ID = "copernicus-dem-glo30-licence"
ATTRIBUTION = "Copernicus DEM GLO-30 © DLR e.V. 2010-2014 and © Airbus 2014-2018, provided under COPERNICUS by the EU and ESA"


def tile_name(lat: float, lon: float) -> str:
    la, lo = math.floor(lat), math.floor(lon)
    ns = f"N{la:02d}" if la >= 0 else f"S{-la:02d}"
    ew = f"E{lo:03d}" if lo >= 0 else f"W{-lo:03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def tile_url(lat: float, lon: float) -> str:
    n = tile_name(lat, lon)
    return f"{BASE}/{n}/{n}.tif"


def terrarium_encode(height_m: np.ndarray) -> np.ndarray:
    if not np.isfinite(height_m).all():
        raise IngestionError("DEM window contains nonfinite heights")
    v = height_m.astype("float64") + 32768.0
    if (v < 0).any() or (v >= 65536).any():
        raise IngestionError("heights outside the Terrarium range")
    r = np.floor(v / 256.0)
    g = np.floor(v - r * 256.0)
    b = np.floor((v - np.floor(v)) * 256.0)
    return np.stack([r, g, b], axis=-1).astype("uint8")


def terrarium_decode(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype("float64")
    return rgb[..., 0] * 256.0 + rgb[..., 1] + rgb[..., 2] / 256.0 - 32768.0


@dataclass
class DemWindow:
    png: bytes
    bounds: tuple[float, float, float, float]
    width: int
    height: int
    min_m: float
    max_m: float
    source_url: str
    source_crs: str
    resolution_deg: tuple[float, float]


def read_dem_window(bbox: tuple[float, float, float, float], buffer_deg: float = 0.01):
    """Original GLO-30 heights for the buffered bbox: (heights, transform, crs, url)."""
    west, south, east, north = bbox
    west, south, east, north = west - buffer_deg, south - buffer_deg, east + buffer_deg, north + buffer_deg
    if math.floor(west) != math.floor(east) or math.floor(south) != math.floor(north):
        raise IngestionError("AOI window crosses a 1° DEM tile edge; mosaic not implemented")
    url = tile_url(south, west)
    with rasterio.Env(**GDAL_ENV), rasterio.open(url) as src:
        win = from_bounds(west, south, east, north, transform=src.transform)
        win = win.round_offsets().round_lengths()
        h = src.read(1, window=win, resampling=Resampling.nearest).astype("float32")
        if src.nodata is not None and (h == src.nodata).any():
            raise IngestionError("DEM window contains nodata")
        return h, src.window_transform(win), src.crs.to_string(), url


def encode_dem(heights: np.ndarray, transform, crs: str, source_url: str) -> DemWindow:
    if crs not in ("EPSG:4326", "OGC:CRS84"):
        raise IngestionError(f"DEM must be geographic (EPSG:4326), got {crs}")
    h = heights.astype("float64")
    hgt, wid = h.shape
    tf = transform
    b = (tf.c, tf.f + tf.e * hgt, tf.c + tf.a * wid, tf.f)
    img = Image.fromarray(terrarium_encode(h), mode="RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return DemWindow(
        png=buf.getvalue(),
        bounds=tuple(round(v, 8) for v in b),  # type: ignore[arg-type]
        width=wid,
        height=hgt,
        min_m=float(h.min()),
        max_m=float(h.max()),
        source_url=source_url,
        source_crs=crs,
        resolution_deg=(abs(tf.a), abs(tf.e)),
    )
