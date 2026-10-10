"""Bounded Overpass query for mapped canals (T2.1 OSM fast path, T2.3).

Keeps OSM ids, every tag, the exact query text and the retrieval timestamp.
Observed geometry only: no hydraulic topology is derived here.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, mapping

from aabflow.domain.ids import source_id

from ..common import FetchResult, IngestionError, http_request

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
LICENSE_ID = "ODbL-1.0"
ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"
WATERWAY_CLASSES = ("canal", "ditch", "drain")


def build_query(bbox: tuple[float, float, float, float], timeout_s: int = 90) -> str:
    """Overpass QL over (south, west, north, east); bbox arrives as (west, south, east, north)."""
    west, south, east, north = bbox
    if not (west < east and south < north):
        raise IngestionError("bbox must be (west, south, east, north)")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise IngestionError("latitudes out of range: check lon/lat order")
    classes = "|".join(WATERWAY_CLASSES)
    b = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return f'[out:json][timeout:{timeout_s}];\n(\n  way["waterway"~"^({classes})$"]({b});\n);\nout geom tags;'


def fetch(query: str, url: str = OVERPASS_URL) -> FetchResult:
    return http_request("POST", url, data={"data": query}, timeout=180)


def to_features(payload: dict[str, Any]) -> list[dict]:
    """Overpass JSON → GeoJSON features with namespaced ids and untouched tags."""
    if "elements" not in payload:
        raise IngestionError("Overpass payload has no 'elements'")
    feats = []
    seen = set()
    for el in payload["elements"]:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        sid = source_id("osm", f"way/{el['id']}")
        if sid in seen:
            raise IngestionError(f"duplicate OSM element {sid}")
        seen.add(sid)
        line = LineString([(p["lon"], p["lat"]) for p in geom])
        tags = dict(el.get("tags") or {})
        if tags.get("waterway") not in WATERWAY_CLASSES:
            raise IngestionError(f"{sid}: unexpected waterway {tags.get('waterway')!r}")
        feats.append(
            {
                "type": "Feature",
                "id": sid,
                "geometry": mapping(line),
                "properties": {
                    "source_feature_id": sid,
                    "provider": "osm",
                    "osm_type": "way",
                    "osm_id": el["id"],
                    "waterway": tags.get("waterway"),
                    "name": tags.get("name:en") or tags.get("name"),
                    "tags": tags,
                    "observed": True,
                    "license": LICENSE_ID,
                },
            }
        )
    feats.sort(key=lambda f: f["properties"]["osm_id"])
    return feats


def feature_collection(features: list[dict], query: str, retrieved_at: str, osm_base: str | None):
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "provider": "osm",
            "endpoint": OVERPASS_URL,
            "query": query,
            "retrieved_at": retrieved_at,
            "osm_base_timestamp": osm_base,
            "attribution": ATTRIBUTION,
            "license": LICENSE_ID,
            "meaning": "Observed mapped geometry/classification only; not hydraulic topology.",
        },
    }
