"""Display imagery: documented RGB stretch, north-up reprojection, WGS84 corners (T2.4 step 8).

The display image is for the map only; it is not scientific reflectance data.

Stretch (``STRETCH_ID``): physical reflectance (published scale/offset) of the red,
green and blue 10 m bands; one shared linear stretch for all three bands from the
2nd to the 98th percentile of valid (SCL-screened) pixels in the window; clip to
[0, 1]; gamma 1/1.4 (``v ** (1/1.4)``); scale to 8-bit. Invalid pixels are
transparent (alpha 0). The image is reprojected with bilinear resampling to an
EPSG:3857 grid so MapLibre's image source places it exactly using four WGS84 corners.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject

STRETCH_ID = "s2-rgb-shared-p2-p98-gamma1.4-v1"
GAMMA = 1.4
DISPLAY_CRS = "EPSG:3857"


@dataclass
class DisplayImage:
    webp: bytes
    width: int
    height: int
    corners_wgs84: list[tuple[float, float]]  # TL, TR, BR, BL (lon, lat)
    bounds_wgs84: tuple[float, float, float, float]
    stretch: dict


def stretch_params(rgb_refl: np.ndarray, valid: np.ndarray, lo_pct=2.0, hi_pct=98.0) -> dict:
    """Shared percentile bounds over valid pixels of all three bands."""
    vals = rgb_refl[:, valid]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        raise ValueError("no valid pixels to derive a display stretch")
    lo, hi = np.percentile(vals, [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1e-6
    return {
        "stretch_id": STRETCH_ID,
        "input": "surface reflectance (scale/offset from STAC raster:bands)",
        "bands": ["red", "green", "blue"],
        "low_percentile": lo_pct,
        "high_percentile": hi_pct,
        "low_reflectance": float(lo),
        "high_reflectance": float(hi),
        "gamma": GAMMA,
        "invalid_pixels": "transparent (SCL classes 0,1,3,8,9,10,11)",
        "note": "Display stretch only; not scientific reflectance data.",
    }


def apply_stretch(rgb_refl: np.ndarray, params: dict) -> np.ndarray:
    lo, hi = params["low_reflectance"], params["high_reflectance"]
    v = np.clip((rgb_refl - lo) / (hi - lo), 0.0, 1.0)
    v = np.where(np.isfinite(v), v, 0.0) ** (1.0 / params["gamma"])
    return (v * 255.0 + 0.5).astype("uint8")


def corners_from_bounds(west: float, south: float, east: float, north: float):
    return [(west, north), (east, north), (east, south), (west, south)]


def render_display(
    rgb_refl: np.ndarray,  # (3, H, W) float reflectance in source CRS
    valid: np.ndarray,  # (H, W) bool
    src_crs: str,
    src_transform,
    quality: int = 90,
) -> DisplayImage:
    params = stretch_params(rgb_refl, valid)
    rgb8 = apply_stretch(rgb_refl, params)
    alpha = np.where(valid, 255, 0).astype("uint8")
    src = np.concatenate([rgb8, alpha[None]], axis=0)
    h, w = valid.shape
    left, bottom, right, top = array_bounds(h, w, src_transform)
    dst_tf, dw, dh = calculate_default_transform(
        CRS.from_string(src_crs), CRS.from_string(DISPLAY_CRS), w, h, left, bottom, right, top
    )
    dst = np.zeros((4, dh, dw), dtype="uint8")
    for i in range(4):
        reproject(
            src[i],
            dst[i],
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_tf,
            dst_crs=DISPLAY_CRS,
            resampling=Resampling.nearest if i == 3 else Resampling.bilinear,
            src_nodata=None,
            dst_nodata=0,
        )
    mb = array_bounds(dh, dw, dst_tf)  # (west, south, east, north) in 3857
    # A 3857 rectangle is a lon/lat rectangle: transform the two corners exactly.
    t = Transformer.from_crs(DISPLAY_CRS, "EPSG:4326", always_xy=True)
    w_, s_ = t.transform(mb[0], mb[1])
    e_, n_ = t.transform(mb[2], mb[3])
    wgs = (w_, s_, e_, n_)
    img = Image.fromarray(np.moveaxis(dst, 0, -1), mode="RGBA")
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    params = {
        **params,
        "display_crs": DISPLAY_CRS,
        "resampling": "bilinear (RGB), nearest (alpha)",
        "width": dw,
        "height": dh,
    }
    return DisplayImage(
        webp=buf.getvalue(),
        width=dw,
        height=dh,
        corners_wgs84=[(round(x, 8), round(y, 8)) for x, y in corners_from_bounds(*wgs)],
        bounds_wgs84=tuple(round(v, 8) for v in wgs),  # type: ignore[arg-type]
        stretch=params,
    )


def save_png_overlay(path: Path, image: Image.Image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path
