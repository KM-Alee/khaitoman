"""Read-only access to published pilot packages (STREAMS.md file contract, T2.6).

Packages live in ``<data>/pilots/<pilot_id>/<pilot_version>/`` and are listed in
``<data>/pilots/index.json``. Everything here is read-only and cached by the
package manifest's modification time, so republishing a version is visible
without a restart while immutable versions are parsed once.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aabflow.api.errors import DomainError, not_found
from aabflow.domain.hashes import file_sha256
from aabflow.domain.schemas import (
    Asset,
    Edge,
    ErrorCode,
    EvidenceRecord,
    FieldRecord,
    InterventionInstance,
    InterventionType,
    Node,
    Pilot,
    PilotManifest,
    RosterWindow,
    ServiceReference,
    SoilProfile,
)

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
SERVABLE_SUFFIXES = {".geojson", ".json", ".webp", ".png", ".jpg", ".jpeg"}
CONTENT_TYPES = {
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def safe_id(value: str, kind: str) -> str:
    if not SAFE_ID.match(value or "") or ".." in value:
        raise not_found(kind, value)
    return value


@dataclass
class PilotPackage:
    pilot_id: str
    pilot_version: str
    directory: Path
    pilot: Pilot
    manifest: PilotManifest | None
    fields: dict[str, FieldRecord]
    field_features: dict[str, dict[str, Any]]
    nodes: dict[str, Node]
    edges: dict[str, Edge]
    roster: dict[str, list[RosterWindow]]
    service_references: list[ServiceReference]
    assets: dict[str, Asset]
    intervention_types: dict[str, InterventionType]
    instances: dict[str, InterventionInstance]
    soils: dict[str, SoilProfile]
    evidence: dict[str, EvidenceRecord]
    resource_status: Any = None
    weather_index: Any = None
    terrain: dict[str, Any] | None = None
    imagery_corners: dict[str, dict[str, Any]] = field(default_factory=dict)
    package_hash: str = ""

    # ----------------------------------------------------------------- graph
    def upstream_edge(self, node_id: str) -> Edge | None:
        for e in self.edges.values():
            if e.downstream_node_id == node_id:
                return e
        return None

    def route_edge_ids(self, field_id: str) -> list[str]:
        """Edges from the source down to the field's outlet (source-first order)."""
        f = self.fields[field_id]
        out: list[str] = []
        node = f.outlet_node_id
        seen: set[str] = set()
        while True:
            e = self.upstream_edge(node)
            if e is None or e.edge_id in seen:
                break
            seen.add(e.edge_id)
            out.append(e.edge_id)
            node = e.upstream_node_id
        return list(reversed(out))

    def file_listed(self, rel: str) -> bool:
        if self.manifest is None:
            return True
        return rel == "manifest.json" or any(f.path == rel for f in self.manifest.files)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _opt_json(path: Path) -> Any:
    return _read_json(path) if path.exists() else None


class PilotRepository:
    def __init__(self, pilots_dir: Path):
        self.root = Path(pilots_dir)
        self._cache: dict[tuple[str, str], tuple[float, PilotPackage]] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- index
    def index(self) -> list[dict[str, Any]]:
        p = self.root / "index.json"
        if not p.exists():
            return []
        raw = _read_json(p)
        rows = raw.get("pilots", []) if isinstance(raw, dict) else raw
        out = []
        for r in rows:
            if not isinstance(r, dict) or "pilot_id" not in r or "pilot_version" not in r:
                continue
            if (self.root / r["pilot_id"] / r["pilot_version"] / "pilot.json").exists():
                out.append(r)
        return out

    def versions(self, pilot_id: str) -> list[str]:
        return [r["pilot_version"] for r in self.index() if r["pilot_id"] == pilot_id]

    def latest_version(self, pilot_id: str) -> str:
        vs = self.versions(pilot_id)
        if not vs:
            raise not_found("pilot_id", pilot_id)
        return vs[-1]

    def published(self) -> list[PilotPackage]:
        out = []
        for r in self.index():
            try:
                out.append(self.package(r["pilot_id"], r["pilot_version"]))
            except DomainError:
                continue
        return out

    # --------------------------------------------------------------- package
    def package(self, pilot_id: str, pilot_version: str | None = None) -> PilotPackage:
        safe_id(pilot_id, "pilot_id")
        version = pilot_version or self.latest_version(pilot_id)
        safe_id(version, "pilot_version")
        if version not in self.versions(pilot_id):
            if not self.versions(pilot_id):
                raise not_found("pilot_id", pilot_id)
            raise not_found("pilot_version", f"{pilot_id}/{version}")
        d = self.root / pilot_id / version
        stamp_file = d / "manifest.json" if (d / "manifest.json").exists() else d / "pilot.json"
        stamp = stamp_file.stat().st_mtime
        key = (pilot_id, version)
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == stamp:
                return hit[1]
        pkg = self._load(pilot_id, version, d)
        with self._lock:
            self._cache[key] = (stamp, pkg)
        return pkg

    def _load(self, pilot_id: str, version: str, d: Path) -> PilotPackage:
        try:
            pilot = Pilot.model_validate(_read_json(d / "pilot.json"))
            manifest = None
            if (d / "manifest.json").exists():
                manifest = PilotManifest.model_validate(_read_json(d / "manifest.json"))
            fields: dict[str, FieldRecord] = {}
            features: dict[str, dict[str, Any]] = {}
            fc = _opt_json(d / "fields.geojson") or {"features": []}
            for feat in fc.get("features", []):
                props = {k: v for k, v in (feat.get("properties") or {}).items() if k in FieldRecord.model_fields}
                rec = FieldRecord.model_validate(props)
                fields[rec.field_id] = rec
                features[rec.field_id] = feat
            net = _opt_json(d / "network.json") or {"nodes": [], "edges": []}
            nodes = {n["node_id"]: Node.model_validate(n) for n in net.get("nodes", [])}
            edges = {e["edge_id"]: Edge.model_validate(e) for e in net.get("edges", [])}
            roster_raw = _opt_json(d / "roster.json") or {"seasons": {}}
            roster = {
                sid: [RosterWindow.model_validate(w) for w in ws]
                for sid, ws in (roster_raw.get("seasons", roster_raw) or {}).items()
            }
            refs = [ServiceReference.model_validate(r) for r in _opt_json(d / "service_reference.json") or []]
            assets = {a["asset_id"]: Asset.model_validate(a) for a in _opt_json(d / "assets.json") or []}
            iv = _opt_json(d / "interventions.json") or {}
            types = {t["type_id"]: InterventionType.model_validate(t) for t in iv.get("types", [])}
            instances = {
                i["instance_id"]: InterventionInstance.model_validate(i) for i in iv.get("instances", [])
            }
            soils = {s["soil_profile_id"]: SoilProfile.model_validate(s) for s in _opt_json(d / "soils.json") or []}
            evidence = {e["evidence_id"]: EvidenceRecord.model_validate(e) for e in _opt_json(d / "evidence.json") or []}
        except (ValueError, KeyError, TypeError) as exc:
            raise DomainError(
                ErrorCode.ASSET_UNAVAILABLE, f"pilot package {pilot_id}/{version} failed to parse: {exc}"
            ) from exc
        terrain = None
        if (d / "terrain" / "dem.json").exists() and (d / "terrain" / "dem.png").exists():
            terrain = _read_json(d / "terrain" / "dem.json")
        corners: dict[str, dict[str, Any]] = {}
        for img in pilot.imagery:
            side = (d / img.display_image_ref).with_suffix(".json")
            if side.exists():
                try:
                    corners[img.scene_id] = _read_json(side)
                except ValueError:
                    pass
        pkg_hash = pilot.package_sha256 or (
            file_sha256(d / "manifest.json") if (d / "manifest.json").exists() else file_sha256(d / "pilot.json")
        )
        return PilotPackage(
            pilot_id=pilot_id,
            pilot_version=version,
            directory=d,
            pilot=pilot,
            manifest=manifest,
            fields=fields,
            field_features=features,
            nodes=nodes,
            edges=edges,
            roster=roster,
            service_references=refs,
            assets=assets,
            intervention_types=types,
            instances=instances,
            soils=soils,
            evidence=evidence,
            resource_status=_opt_json(d / "resource_status.json"),
            weather_index=_opt_json(d / "weather" / "index.json"),
            terrain=terrain,
            imagery_corners=corners,
            package_hash=pkg_hash,
        )

    # ----------------------------------------------------------------- lookup
    def find_field(self, field_id: str, pilot_id: str | None, pilot_version: str | None) -> PilotPackage:
        candidates = (
            [self.package(pilot_id, pilot_version)]
            if pilot_id
            else [p for p in self.published() if pilot_version in (None, p.pilot_version)]
        )
        # newest version first when unspecified
        for pkg in reversed(candidates):
            if field_id in pkg.fields:
                return pkg
        raise not_found("field_id", field_id)

    def asset_path(self, pilot_id: str, version: str, rel: str) -> Path:
        """Validated path of a servable package file; raises NOT_FOUND otherwise."""
        pkg = self.package(pilot_id, version)
        if not rel or "\\" in rel or rel.startswith("/") or any(p in ("", ".", "..") for p in rel.split("/")):
            raise not_found("asset", rel)
        p = (pkg.directory / rel).resolve()
        base = pkg.directory.resolve()
        if base not in p.parents or not p.is_file() or p.suffix.lower() not in SERVABLE_SUFFIXES:
            raise not_found("asset", rel)
        if not pkg.file_listed(rel):
            raise not_found("asset", rel)
        return p
