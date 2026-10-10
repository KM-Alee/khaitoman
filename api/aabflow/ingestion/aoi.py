"""AOI geometry, metric CRS selection, and onboarding limits (T2.2).

Coordinates are EPSG:4326 ``(lon, lat)``. Areas are always computed in a metric
CRS (the UTM zone that contains the AOI centroid), never in degrees².
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import shapely
import shapely.validation
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import transform

# Published Mungi search extent (PRD §2.1, T2.2): discovery only, not a pilot.
DISCOVERY_EXTENT = {
    "bbox": (72.133333, 30.55, 72.8, 31.033333),
    "scope": "published_search_extent",
    "source": "https://doi.org/10.3390/w14030405",
    "note": "Broad literature search box; supports discovery only (T2.2).",
}

MAX_AOI_AREA_M2 = 25_000_000.0  # T2.2 onboarding limit (configurable)
MAX_SCENE_PIXELS = 25_000_000  # per selected scene


class AoiError(ValueError):
    pass


def utm_crs_for(lon: float, lat: float) -> CRS:
    if not (-180 <= lon <= 180 and -80 <= lat <= 84):
        raise AoiError(f"coordinates out of UTM range or swapped: lon={lon}, lat={lat}")
    zone = math.floor((lon + 180) / 6) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def to_metric(geom, crs: CRS):
    t = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return transform(t.transform, geom)


def to_wgs84(geom, crs: CRS):
    t = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    return transform(t.transform, geom)


@dataclass(frozen=True)
class Aoi:
    geometry: Polygon  # EPSG:4326
    metric_crs: CRS

    @classmethod
    def from_geojson(cls, gj: dict) -> Aoi:
        g = gj
        if gj.get("type") == "FeatureCollection":
            if len(gj["features"]) != 1:
                raise AoiError("AOI FeatureCollection must contain exactly one feature")
            g = gj["features"][0]["geometry"]
        elif gj.get("type") == "Feature":
            g = gj["geometry"]
        geom = shape(g)
        return cls.from_geometry(geom)

    @classmethod
    def from_bbox(cls, west: float, south: float, east: float, north: float) -> Aoi:
        if west >= east or south >= north:
            raise AoiError("bbox must be west<east and south<north (lon/lat order)")
        return cls.from_geometry(box(west, south, east, north))

    @classmethod
    def from_geometry(cls, geom) -> Aoi:
        if geom.geom_type != "Polygon":
            raise AoiError(f"AOI must be a single Polygon, got {geom.geom_type}")
        if not geom.is_valid:
            raise AoiError(f"AOI polygon invalid: {shapely.validation.explain_validity(geom)}")
        minx, miny, maxx, maxy = geom.bounds
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise AoiError("AOI coordinates outside lon/lat range (check axis order)")
        c = geom.centroid
        return cls(geometry=geom, metric_crs=utm_crs_for(c.x, c.y))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return tuple(round(v, 7) for v in self.geometry.bounds)  # type: ignore[return-value]

    @property
    def centroid(self) -> tuple[float, float]:
        c = self.geometry.centroid
        return (c.x, c.y)

    @property
    def metric_geometry(self):
        return to_metric(self.geometry, self.metric_crs)

    @property
    def area_m2(self) -> float:
        return float(self.metric_geometry.area)

    @property
    def metric_crs_id(self) -> str:
        return f"EPSG:{self.metric_crs.to_epsg()}"

    def check_limits(self, max_area_m2: float = MAX_AOI_AREA_M2) -> None:
        if self.area_m2 > max_area_m2:
            raise AoiError(
                f"AOI area {self.area_m2 / 1e6:.2f} km² exceeds onboarding limit "
                f"{max_area_m2 / 1e6:.2f} km²"
            )
        if self.area_m2 <= 0:
            raise AoiError("AOI has zero area")

    def estimate_pixels(self, resolution_m: float = 10.0, buffer_m: float = 0.0) -> int:
        minx, miny, maxx, maxy = self.metric_geometry.buffer(buffer_m).bounds
        return int(
            math.ceil((maxx - minx) / resolution_m) * math.ceil((maxy - miny) / resolution_m)
        )

    def feature_collection(self, properties: dict | None = None) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "aoi",
                    "geometry": mapping(self.geometry),
                    "properties": properties or {},
                }
            ],
        }


def disjoint(a: Aoi, b: Aoi) -> bool:
    return not a.geometry.intersects(b.geometry)
