"""Pilot package validation (T2.3, T2.6, AT01).

``validate_package(dir)`` returns a list of human-readable errors (empty = valid).
Rules: manifest version/paths/duplicates/sizes/hashes/unlisted files; schema
parsing of every file; duplicate ids; pilot ownership of ids; cross-references;
a directed tree rooted at one source with every field outlet reachable; delivery
factors in (0, 1]; ≥2 reaches with distinct factors below every accounting node;
exclusive roster windows; exactly 30 valid, non-overlapping fields with metric
areas matching their geometry; existing pond and shared pump; all five
intervention categories, ≤2 shared repairs, pond size options per field held
mutually exclusive and sized at 0.5/1/1.5 × 75 mm; ≥2 soil archetypes; weather
series complete for ≥10 years; imagery refs and corners present.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd
from pydantic import ValidationError
from shapely.geometry import shape

from aabflow.domain.hashes import file_sha256
from aabflow.domain.schemas import (
    ActionCategory,
    Asset,
    AssetKind,
    Edge,
    EvidenceRecord,
    Field_,
    InterventionInstance,
    InterventionType,
    Node,
    NodeKind,
    Pilot,
    PilotManifest,
    RightsBasis,
    RosterWindow,
    ServiceReference,
    SoilProfile,
    WeatherSeries,
)

from ..aoi import Aoi, to_metric
from .bundle import BundleError, safe_relpath

REQUIRED_FILES = (
    "pilot.json",
    "aoi.geojson",
    "fields.geojson",
    "fields_raw.geojson",
    "review_log.json",
    "canals.geojson",
    "network.json",
    "roster.json",
    "service_reference.json",
    "assets.json",
    "interventions.json",
    "soils.json",
    "evidence.json",
    "resource_status.json",
    "manifest.json",
    "weather/index.json",
)
ALLOWED_SUFFIXES = {".json", ".geojson", ".webp", ".png", ".parquet", ".gpkg"}
MAX_FILE_BYTES = 100 * 1024 * 1024
REQUIRED_FIELDS = 30
POND_IRRIGATIONS = (0.5, 1.0, 1.5)
IRRIGATION_MM = 75.0
MIN_WEATHER_YEARS = 10


class PackageValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} package validation error(s): " + "; ".join(errors[:8]))
        self.errors = errors


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def check_manifest(root: Path, errors: list[str]) -> PilotManifest | None:
    mp = root / "manifest.json"
    if not mp.exists():
        errors.append("manifest.json missing")
        return None
    try:
        m = PilotManifest.model_validate(_load(mp))
    except (ValidationError, ValueError) as exc:
        errors.append(f"manifest.json invalid: {exc}")
        return None
    seen: set[str] = set()
    for f in m.files:
        try:
            rel = safe_relpath(f.path)
        except BundleError as exc:
            errors.append(f"manifest: {exc}")
            continue
        if rel.lower() in seen:
            errors.append(f"manifest: duplicate path {rel}")
        seen.add(rel.lower())
        if PurePosixPath(rel).suffix.lower() not in ALLOWED_SUFFIXES:
            errors.append(f"manifest: format not allowed {rel}")
        p = root / rel
        if p.is_symlink() or not p.is_file():
            errors.append(f"manifest: missing file {rel}")
            continue
        if f.size_bytes > MAX_FILE_BYTES or p.stat().st_size != f.size_bytes:
            errors.append(f"manifest: size mismatch or too large {rel}")
        if file_sha256(p) != f.sha256:
            errors.append(f"manifest: sha256 mismatch {rel}")
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root))
            if rel != "manifest.json" and rel.lower() not in seen:
                errors.append(f"unlisted file {rel}")
    return m


def _dupes(ids: list[str], what: str, errors: list[str]) -> None:
    for k, n in Counter(ids).items():
        if n > 1:
            errors.append(f"duplicate {what} id {k}")


def check_graph(nodes: list[Node], edges: list[Edge], errors: list[str]) -> dict[str, str]:
    """Directed tree check; returns child -> parent node map."""
    ids = {n.node_id for n in nodes}
    parent: dict[str, str] = {}
    for e in edges:
        for nid in (e.upstream_node_id, e.downstream_node_id):
            if nid not in ids:
                errors.append(f"edge {e.edge_id}: dangling node {nid}")
        if e.upstream_node_id == e.downstream_node_id:
            errors.append(f"edge {e.edge_id}: self loop")
        if e.downstream_node_id in parent:
            errors.append(f"node {e.downstream_node_id}: more than one upstream edge (not a tree)")
        parent[e.downstream_node_id] = e.upstream_node_id
        if not 0 < e.delivery_factor <= 1:
            errors.append(f"edge {e.edge_id}: delivery_factor outside (0,1]")
        for c in e.capacities:
            if c.end <= c.start:
                errors.append(f"edge {e.edge_id}: capacity interval end <= start")
        for s, t in e.closures:
            if t <= s:
                errors.append(f"edge {e.edge_id}: closure end <= start")
        if e.geometry_ref is None and e.source_feature_ids:
            errors.append(f"edge {e.edge_id}: assumed edge must not cite source features")
    roots = [n for n in nodes if n.node_id not in parent]
    if len(roots) != 1 or roots[0].kind != NodeKind.source:
        errors.append(
            f"graph must have exactly one source root, found {[r.node_id for r in roots]}"
        )
    for n in nodes:  # cycle / reachability: walk up to the root
        seen = {n.node_id}
        cur = n.node_id
        while cur in parent:
            cur = parent[cur]
            if cur in seen:
                errors.append(f"cycle through node {n.node_id}")
                break
            seen.add(cur)
    return parent


def _ancestors(node: str, parent: dict[str, str]) -> list[str]:
    out = []
    seen = set()
    while node in parent and node not in seen:
        seen.add(node)
        node = parent[node]
        out.append(node)
    return out


def check_roster(roster: dict[str, list[RosterWindow]], errors: list[str]) -> None:
    for sid, wins in roster.items():
        by_node: dict[str, list[RosterWindow]] = defaultdict(list)
        for w in wins:
            if w.end <= w.start:
                errors.append(f"roster {w.window_id}: end <= start")
            if w.basis == RightsBasis.time and not (w.rate_m3_s and w.rate_m3_s > 0):
                errors.append(f"roster {w.window_id}: time basis needs rate_m3_s > 0")
            if w.basis == RightsBasis.volume and w.volume_cap_m3 is None:
                errors.append(f"roster {w.window_id}: volume basis needs volume_cap_m3")
            by_node[w.outlet_node_id].append(w)
        for node, ws in by_node.items():
            ws = sorted(ws, key=lambda w: (w.start, w.window_id))
            for a, b in pairwise(ws):
                if b.start < a.end:
                    errors.append(
                        f"roster {sid}: windows {a.window_id} and {b.window_id} overlap at {node}"
                    )


def check_fields(features: list[dict], aoi: Aoi, errors: list[str]) -> list[Field_]:
    out = []
    geoms = {}
    aoi_m = aoi.metric_geometry.buffer(1.0)
    for f in features:
        try:
            rec = Field_.model_validate(f["properties"])
        except ValidationError as exc:
            errors.append(
                f"field {f.get('id')}: {exc.errors()[0]['msg']} ({exc.errors()[0]['loc']})"
            )
            continue
        if f.get("id") != rec.field_id or rec.geometry_ref != rec.field_id:
            errors.append(f"field {rec.field_id}: feature id / geometry_ref mismatch")
        g = shape(f["geometry"])
        if g.geom_type != "Polygon" or not g.is_valid or g.is_empty:
            errors.append(f"field {rec.field_id}: geometry must be one valid polygon")
            continue
        gm = to_metric(g, aoi.metric_crs)
        if abs(gm.area - rec.gross_area_m2) > max(1.0, 0.005 * gm.area):
            errors.append(
                f"field {rec.field_id}: gross_area_m2 {rec.gross_area_m2} != metric area {gm.area:.1f}"
            )
        if abs(rec.gross_area_ha * 10_000 - rec.gross_area_m2) > 1.0:
            errors.append(f"field {rec.field_id}: gross_area_ha inconsistent with m²")
        if not aoi_m.contains(gm):
            errors.append(f"field {rec.field_id}: outside the AOI")
        geoms[rec.field_id] = gm
        out.append(rec)
    if len(out) != REQUIRED_FIELDS:
        errors.append(f"{len(out)} valid reviewed fields; exactly {REQUIRED_FIELDS} required")
    ids = list(geoms)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if geoms[a].intersection(geoms[b]).area > 1.0:
                errors.append(f"fields {a} and {b} overlap")
    return out


def validate_package(root: Path) -> list[str]:
    root = Path(root)
    errors: list[str] = []
    for r in REQUIRED_FILES:
        if not (root / r).is_file():
            errors.append(f"required file missing: {r}")
    if errors:
        return errors
    manifest = check_manifest(root, errors)
    try:
        pilot = Pilot.model_validate(_load(root / "pilot.json"))
    except ValidationError as exc:
        return [*errors, f"pilot.json invalid: {exc}"]
    pid = pilot.pilot_id
    if manifest and (manifest.pilot_id != pid or manifest.pilot_version != pilot.pilot_version):
        errors.append("manifest pilot id/version differ from pilot.json")
    aoi = Aoi.from_geojson(_load(root / pilot.aoi_geojson_ref))
    if abs(aoi.area_m2 - pilot.aoi_area_m2) > 1.0 or aoi.metric_crs_id != pilot.metric_crs:
        errors.append("pilot AOI area/metric CRS inconsistent with aoi.geojson")

    def own(i: str, what: str) -> None:
        if not i.startswith(f"{pid}:"):
            errors.append(f"{what} id {i} does not belong to {pid}")

    try:
        evidence = [EvidenceRecord.model_validate(e) for e in _load(root / "evidence.json")]
        nodes = [Node.model_validate(n) for n in _load(root / "network.json")["nodes"]]
        edges = [Edge.model_validate(e) for e in _load(root / "network.json")["edges"]]
        roster = {
            k: [RosterWindow.model_validate(w) for w in v]
            for k, v in _load(root / "roster.json")["seasons"].items()
        }
        services = [
            ServiceReference.model_validate(s) for s in _load(root / "service_reference.json")
        ]
        assets = [Asset.model_validate(a) for a in _load(root / "assets.json")]
        itv = _load(root / "interventions.json")
        types = [InterventionType.model_validate(t) for t in itv["types"]]
        instances = [InterventionInstance.model_validate(i) for i in itv["instances"]]
        soils = [SoilProfile.model_validate(s) for s in _load(root / "soils.json")]
        weather = [WeatherSeries.model_validate(w) for w in _load(root / "weather/index.json")]
    except (ValidationError, KeyError, TypeError) as exc:
        return [*errors, f"schema error: {exc}"]
    fields = check_fields(_load(root / "fields.geojson")["features"], aoi, errors)

    ev_ids = [e.evidence_id for e in evidence]
    _dupes(ev_ids, "evidence", errors)
    _dupes([f.field_id for f in fields], "field", errors)
    _dupes([n.node_id for n in nodes], "node", errors)
    _dupes([e.edge_id for e in edges], "edge", errors)
    _dupes([a.asset_id for a in assets], "asset", errors)
    _dupes([i.instance_id for i in instances], "intervention instance", errors)
    _dupes([t.type_id for t in types], "intervention type", errors)
    _dupes([w.window_id for ws in roster.values() for w in ws], "roster window", errors)
    _dupes([s.soil_profile_id for s in soils], "soil", errors)
    for i in (
        [f.field_id for f in fields]
        + [n.node_id for n in nodes]
        + [e.edge_id for e in edges]
        + [a.asset_id for a in assets]
        + [i.instance_id for i in instances]
    ):
        own(i, "entity")
    evs = set(ev_ids)

    def cite(ids: list[str], where: str) -> None:
        for e in ids:
            if e not in evs:
                errors.append(f"{where}: unknown evidence id {e}")

    node_by = {n.node_id: n for n in nodes}
    field_by = {f.field_id: f for f in fields}
    edge_ids = {e.edge_id for e in edges}
    asset_by = {a.asset_id: a for a in assets}
    soil_ids = {s.soil_profile_id for s in soils}
    parent = check_graph(nodes, edges, errors)
    for e in edges:
        cite(e.evidence_ids, f"edge {e.edge_id}")
    for f in fields:
        cite(f.evidence_ids, f"field {f.field_id}")
        if f.outlet_node_id not in node_by or node_by[f.outlet_node_id].kind != NodeKind.outlet:
            errors.append(f"field {f.field_id}: outlet {f.outlet_node_id} missing or not an outlet")
        if f.soil_profile_id not in soil_ids:
            errors.append(f"field {f.field_id}: unknown soil {f.soil_profile_id}")
    soil_type = {s.soil_profile_id: s.engine_soil_type for s in soils}
    if len({soil_type.get(f.soil_profile_id) for f in fields} - {None}) < 2:
        errors.append("fields use fewer than 2 soil archetypes")

    # Roster references and reach structure below each accounting node.
    check_roster(roster, errors)
    heads = set()
    for sid, ws in roster.items():
        for w in ws:
            if w.field_id not in field_by:
                errors.append(f"roster {w.window_id}: unknown field {w.field_id}")
                continue
            heads.add(w.outlet_node_id)
            fo = field_by[w.field_id].outlet_node_id
            if w.outlet_node_id != fo and w.outlet_node_id not in _ancestors(fo, parent):
                errors.append(f"roster {w.window_id}: accounting node not on the field's route")
        covered = {w.field_id for w in ws}
        if covered != set(field_by):
            errors.append(f"roster {sid}: {len(set(field_by) - covered)} fields have no windows")
    for h in heads:
        below = [e for e in edges if h in _ancestors(e.downstream_node_id, parent)]
        if len(below) < 2 or len({e.delivery_factor for e in below}) < 2:
            errors.append(f"watercourse at {h}: needs ≥2 reaches with distinct delivery factors")
    for s in services:
        if s.field_id not in field_by:
            errors.append(f"service reference: unknown field {s.field_id}")
        if s.season_id not in roster:
            errors.append(f"service reference: unknown season {s.season_id}")

    # Assets.
    ponds = [a for a in assets if a.kind == AssetKind.pond and a.existing]
    pumps = [a for a in assets if a.kind == AssetKind.pump and a.existing]
    if not ponds:
        errors.append("no existing pond asset")
    if not any(len(p.field_ids) >= 2 for p in pumps):
        errors.append("no existing shared pump (≥2 fields)")
    for a in assets:
        cite(a.evidence_ids, f"asset {a.asset_id}")
        for fid in a.field_ids:
            if fid not in field_by:
                errors.append(f"asset {a.asset_id}: unknown field {fid}")
        if a.node_id is not None and a.node_id not in node_by:
            errors.append(f"asset {a.asset_id}: unknown node {a.node_id}")
        if a.existing and a.commissioned_at is None:
            errors.append(f"asset {a.asset_id}: existing asset needs commissioned_at")
        if a.kind == AssetKind.pond and not (
            a.usable_capacity_m3 and a.surface_area_m2 and a.footprint_m2
        ):
            errors.append(f"asset {a.asset_id}: pond needs capacity, surface and footprint")
        if a.kind == AssetKind.pump and not (
            a.max_rate_m3_h and a.seasonal_cap_m3 and a.cost_per_m3_pkr
        ):
            errors.append(f"asset {a.asset_id}: pump needs max rate, seasonal cap and cost")

    # Interventions.
    type_by = {t.type_id: t for t in types}
    cats = {i.category for i in instances}
    for c in ActionCategory:
        if c not in cats:
            errors.append(f"no intervention instance in category {c.value}")
    repairs = [i for i in instances if i.category == ActionCategory.shared_repair]
    if len(repairs) > 2:
        errors.append(f"{len(repairs)} shared repairs; at most 2 allowed")
    pond_groups: dict[str, list[InterventionInstance]] = defaultdict(list)
    for i in instances:
        cite(i.evidence_ids, f"instance {i.instance_id}")
        t = type_by.get(i.type_id)
        if t is None:
            errors.append(f"instance {i.instance_id}: unknown type {i.type_id}")
        elif t.category != i.category:
            errors.append(f"instance {i.instance_id}: category differs from its type")
        else:
            for k in t.required_parameters:
                if k not in i.parameters:
                    errors.append(f"instance {i.instance_id}: missing parameter {k}")
        for tid in i.target_ids:
            if tid not in field_by and tid not in edge_ids and tid not in asset_by:
                errors.append(f"instance {i.instance_id}: unknown target {tid}")
        if i.category in (
            ActionCategory.leveling,
            ActionCategory.pond,
            ActionCategory.shared_repair,
        ):
            if i.capex_pkr <= 0:
                errors.append(f"instance {i.instance_id}: proposed action needs capex > 0")
            if i.lead_time_days <= 0:
                errors.append(f"instance {i.instance_id}: proposed action needs a lead time")
        if i.category == ActionCategory.shared_repair:
            if not i.shared:
                errors.append(f"instance {i.instance_id}: shared repair must be shared")
            if any(t not in edge_ids for t in i.target_ids):
                errors.append(f"instance {i.instance_id}: repair must target edges")
        if i.category == ActionCategory.pump_supplement and any(
            t not in asset_by or asset_by[t].kind != AssetKind.pump or not asset_by[t].existing
            for t in i.target_ids
        ):
            errors.append(f"instance {i.instance_id}: must target an existing pump")
        if i.category == ActionCategory.pond:
            if not i.mutually_exclusive_group:
                errors.append(f"instance {i.instance_id}: pond needs a mutually exclusive group")
            pond_groups[i.mutually_exclusive_group or i.instance_id].append(i)
    for g, items in pond_groups.items():
        tgt = {tuple(i.target_ids) for i in items}
        if len(tgt) != 1 or len(next(iter(tgt))) != 1 or next(iter(tgt))[0] not in field_by:
            errors.append(f"pond group {g}: must target one field")
            continue
        f = field_by[next(iter(tgt))[0]]
        held = sorted(float(i.parameters.get("irrigations_held", -1)) for i in items)
        if held != list(POND_IRRIGATIONS):
            errors.append(f"pond group {g}: sizes {held} != {list(POND_IRRIGATIONS)} irrigations")
        for i in items:
            want = (
                float(i.parameters.get("irrigations_held", 0))
                * IRRIGATION_MM
                / 1000
                * f.gross_area_m2
            )
            got = float(i.parameters.get("usable_capacity_m3", -1))
            if abs(got - want) > max(0.5, 0.01 * want):
                errors.append(f"instance {i.instance_id}: capacity {got} != {want:.1f} m³")
            if float(i.parameters.get("footprint_m2", 0)) >= f.gross_area_m2:
                errors.append(f"instance {i.instance_id}: footprint leaves no cropped area")

    # Imagery and weather.
    for im in pilot.imagery:
        if not im.scene_id.strip():
            errors.append("imagery: missing scene id")
            continue
        meta = root / f"imagery/{im.scene_id}.json"
        if not meta.is_file() or not (root / im.display_image_ref).is_file():
            errors.append(f"imagery {im.scene_id}: metadata or display image missing")
        if len(im.display_corners_wgs84) != 4:
            errors.append(f"imagery {im.scene_id}: needs 4 corners")
        if im.evidence_id not in evs:
            errors.append(f"imagery {im.scene_id}: unknown evidence {im.evidence_id}")
    if not pilot.imagery:
        errors.append("pilot has no imagery reference")
    if not weather:
        errors.append("no weather series")
    for w in weather:
        for ref, h in ((w.raw_ref, w.source_sha256), (w.normalized_ref, w.normalized_sha256)):
            p = root / ref
            if not p.is_file() or file_sha256(p) != h:
                errors.append(f"weather {w.weather_series_id}: {ref} missing or hash mismatch")
        p = root / w.normalized_ref
        if p.is_file():
            df = pd.read_parquet(p)
            if list(df.columns) != ["Date", "MinTemp", "MaxTemp", "Precipitation", "ReferenceET"]:
                errors.append(
                    f"weather {w.weather_series_id}: unexpected columns {list(df.columns)}"
                )
            else:
                d = pd.to_datetime(df["Date"])
                exp = pd.date_range(w.start, w.end, freq="D")
                if not pd.DatetimeIndex(d).equals(exp) or df.isna().any().any():
                    errors.append(f"weather {w.weather_series_id}: incomplete daily index or NaN")
                full = sum(1 for y, g in d.groupby(d.dt.year) if len(g) >= 365)
                if full < MIN_WEATHER_YEARS:
                    errors.append(
                        f"weather {w.weather_series_id}: {full} complete years < {MIN_WEATHER_YEARS}"
                    )
        if w.evidence_id not in evs:
            errors.append(f"weather {w.weather_series_id}: unknown evidence {w.evidence_id}")
    for r in pilot.source_refs:
        if r not in evs:
            errors.append(f"pilot source ref {r} not in evidence")
    return errors
