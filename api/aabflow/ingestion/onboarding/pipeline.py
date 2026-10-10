"""Onboarding pipeline as callable stages (PRD §5.3, T2.6, F03/AT16).

``acquired_raw → processed → needs_review → reviewed → validated → published``

A *workdir* holds one intake::

    <workdir>/intake.json      state, AOI, source mode, bundle ref, history, review version
    <workdir>/processed/       processed sources + raw Delineate output (process.py)
    <workdir>/review/          review_log.json, state.json, edits_v<N>.json

Entry points used by the API (POST /onboarding …) and the CLI scripts:
``validate_aoi``, ``create_intake``, ``process``, ``apply_review``, ``publish``,
``reproduce_published``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from shapely.geometry import shape

from aabflow import config
from aabflow.domain.hashes import file_sha256
from aabflow.domain.schemas import PilotManifest

from ..aoi import MAX_AOI_AREA_M2, Aoi, AoiError
from ..common import IngestionError, iso, read_json, utc_now, write_json
from ..packages.builder import ReviewedField, build_package
from ..packages.bundle import validate_bundle
from ..packages.validate import PackageValidationError, validate_package
from ..review.fields import ManualEdit, ReviewConfig, review, selected_wgs84
from . import process as proc_mod
from .acquire import AcquisitionConfig, Cancelled, acquire_bundle
from .catalog import resolve_stored_bundle
from .libraries import write_readiness
from .review_input import ReviewRejected, field_edits, network_review, structural_blockers

Progress = Callable[[str, float | None, str], None]
SourceMode = Literal["online", "raw_package"]
CANAL_EXCLUSION_M = 8.0


class VersionConflict(ValueError):
    pass


class StageError(IngestionError):
    pass


class StructuralBlock(StageError):
    """Publish refused because review or package structure is not valid."""

    def __init__(self, blockers: list[str]):
        super().__init__("structural errors block publish: " + "; ".join(blockers))
        self.blockers = blockers


class ReproductionError(StageError):
    """A rebuild did not match the published bytes. The published tree is unchanged."""


def _noop(stage: str, frac: float | None, detail: str) -> None:
    pass


def validate_aoi(geojson: dict) -> dict[str, Any]:
    """Area, bbox and limits before any job starts (raises AoiError on invalid geometry)."""
    aoi = Aoi.from_geojson(geojson)
    blockers, warnings = [], []
    if aoi.area_m2 > MAX_AOI_AREA_M2:
        blockers.append(
            f"AOI {aoi.area_m2 / 1e6:.2f} km² exceeds the {MAX_AOI_AREA_M2 / 1e6:.0f} km² limit"
        )
    if aoi.area_m2 < 1_000_000:
        warnings.append("AOI under 1 km² may not contain 30 reviewable fields")
    return {
        "area_m2": round(aoi.area_m2, 2),
        "bbox": aoi.bbox,
        "centroid": aoi.centroid,
        "metric_crs": aoi.metric_crs_id,
        "estimated_pixels": aoi.estimate_pixels(10.0, AcquisitionConfig.window_buffer_m),
        "warnings": warnings,
        "blockers": blockers,
    }


def _intake_path(workdir: Path) -> Path:
    return Path(workdir) / "intake.json"


def _load(workdir: Path) -> dict:
    p = _intake_path(workdir)
    if not p.exists():
        raise StageError(f"no intake at {workdir}")
    return read_json(p)


def _save(workdir: Path, st: dict) -> dict:
    write_json(_intake_path(workdir), st)
    return st


def _transition(st: dict, state: str, detail: str = "") -> None:
    st["state"] = state
    st.setdefault("history", []).append({"state": state, "at": iso(utc_now()), "detail": detail})


def create_intake(
    intake_id: str,
    aoi_geojson: dict,
    source_mode: SourceMode,
    raw_package_ref: str | None,
    workdir: Path,
    name: str | None = None,
    pilot_id: str | None = None,
    geographic_name_basis: str | None = None,
    parent_canal_feature_id: str | None = None,
    repo_root: Path | None = None,
    data_dir: Path | None = None,
) -> dict:
    workdir = Path(workdir)
    if _intake_path(workdir).exists():
        raise StageError(f"intake already exists at {workdir}")
    v = validate_aoi(aoi_geojson)
    if v["blockers"]:
        raise AoiError("; ".join(v["blockers"]))
    if source_mode not in ("online", "raw_package"):
        raise ValueError(f"unknown source_mode {source_mode!r}")
    if source_mode == "raw_package":
        if not raw_package_ref:
            raise ValueError("raw_package mode needs raw_package_ref")
        root = resolve_stored_bundle(
            raw_package_ref,
            Path(repo_root or config.ROOT),
            Path(data_dir) if data_dir is not None else None,
        )
        b = validate_bundle(root)
        if (
            shape(b.read_json("aoi.geojson")["features"][0]["geometry"])
            .symmetric_difference(Aoi.from_geojson(aoi_geojson).geometry)
            .area
            > 1e-12
        ):
            raise ValueError("raw package AOI differs from the intake AOI")
    workdir.mkdir(parents=True, exist_ok=True)
    st = {
        "intake_id": intake_id,
        "pilot_id": pilot_id,
        "name": name,
        "geographic_name_basis": geographic_name_basis,
        "aoi": aoi_geojson,
        "aoi_check": v,
        "source_mode": source_mode,
        "bundle_ref": raw_package_ref,
        "parent_canal_feature_id": parent_canal_feature_id,
        "review_version": 0,
        "created_at": iso(utc_now()),
        "history": [],
    }
    _transition(st, "created", source_mode)
    return _save(workdir, st)


def _review_items(rv) -> list[dict]:
    return [
        {
            "model_id": e["model_id"],
            "decision": e["decision"],
            "actions": e["actions"],
            "reasons": e["reasons"],
            "metrics": e["metrics"],
        }
        for e in rv.log
        if e["decision"] != "eligible_not_selected" or e["actions"]
    ]


def _exclusions(canals: dict) -> list:
    """Mapped canal/drain lines buffered by a few metres (reviewed fields must not cross them)."""
    from ..aoi import to_metric, to_wgs84

    out = []
    for f in canals["features"]:
        if f["properties"].get("provider") != "osm":
            continue
        g = shape(f["geometry"])
        c = g.centroid
        from ..aoi import utm_crs_for

        crs = utm_crs_for(c.x, c.y)
        out.append(to_wgs84(to_metric(g, crs).buffer(CANAL_EXCLUSION_M), crs))
    return out


def _run_review(workdir: Path, st: dict, edits: list[ManualEdit], reviewer: str | None) -> dict:
    processed = workdir / "processed"
    aoi = Aoi.from_geojson(st["aoi"])
    raw = read_json(processed / "fields_raw.geojson")
    canals = read_json(processed / "canals.geojson")
    cfg = ReviewConfig(**st.get("review_config", {}))
    rv = review(raw, aoi, cfg, manual_edits=edits, exclusion_wgs84=_exclusions(canals))
    rdir = workdir / "review"
    rdir.mkdir(exist_ok=True)
    state_p = rdir / "state.json"
    rs = read_json(state_p) if state_p.exists() else {"id_map": {}, "next_index": 1}
    pid = st.get("pilot_id") or st["intake_id"]
    # Stable ids: once a model id is assigned a field id it keeps it; new ones are
    # numbered north-west → south-east for readable labels.
    sel = sorted(rv.selected, key=lambda c: (-round(c.geom_m.centroid.y, -1), c.geom_m.centroid.x))
    id_map = {k: v for k, v in rs["id_map"].items() if k in {c.model_id for c in sel}}
    used = set(id_map.values())
    nxt = rs.get("next_index", 1)
    for c in sel:
        if c.model_id not in id_map:
            while f"{pid}:field-{nxt:03d}" in used:
                nxt += 1
            id_map[c.model_id] = f"{pid}:field-{nxt:03d}"
            used.add(id_map[c.model_id])
            nxt += 1
    fields = []
    letter = pid.split("-")[-1].upper()[:1] or "F"
    for c in sel:
        fid = id_map[c.model_id]
        fields.append(
            {
                "field_id": fid,
                "label": f"{letter}-{fid.rsplit('-', 1)[-1]}",
                "geometry_wgs84": selected_wgs84(c, aoi.metric_crs),
                "area_m2": c.geom_m.area,
                "source_model_ids": c.source_model_ids,
                "actions": c.actions,
            }
        )
    for e in rv.log:
        e["field_id"] = id_map.get(e["model_id"])
    now = utc_now()
    started = st.get("review_started_at") or iso(now)
    rs = {
        "id_map": id_map,
        "next_index": nxt,
        "fields": fields,
        "summary": {**rv.summary, "review_started_at": started, "review_finished_at": iso(now)},
        "reviewer": reviewer,
        "reviewed_at": iso(now),
    }
    write_json(state_p, rs)
    write_json(
        rdir / "review_log.json",
        {
            "pilot_id": pid,
            "summary": rs["summary"],
            "reviewer": reviewer,
            "reviewed_at": iso(now),
            "id_map": id_map,
            "manual_edits": [vars(e) for e in edits],
            "entries": rv.log,
        },
    )
    write_json(
        processed / "fields_proposed.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": f["field_id"],
                    "geometry": f["geometry_wgs84"],
                    "properties": {k: v for k, v in f.items() if k != "geometry_wgs84"},
                }
                for f in fields
            ],
        },
    )
    return {"review": rv, "state": rs}


def process(
    intake_id: str,
    workdir: Path,
    progress: Progress = _noop,
    should_cancel: Callable[[], bool] = lambda: False,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    acquisition: AcquisitionConfig | None = None,
    inference_cache_only: bool = False,
) -> dict:
    """Acquire (online) or import (raw package), process, run/reuse inference, propose review."""
    workdir = Path(workdir)
    repo_root = Path(repo_root or config.ROOT)
    data_dir = Path(data_dir or config.DATA_DIR)
    st = _load(workdir)
    if st["intake_id"] != intake_id:
        raise StageError("intake id mismatch")
    if st["state"] in ("published",):
        raise StageError("intake already published")
    try:
        if st["source_mode"] == "online" and not st.get("bundle_ref"):
            aoi = Aoi.from_geojson(st["aoi"])
            root = acquire_bundle(
                st.get("pilot_id") or intake_id,
                aoi,
                data_dir,
                acquisition,
                progress=progress,
                should_cancel=should_cancel,
                name=st.get("name"),
                geographic_name_basis=st.get("geographic_name_basis"),
            )
            st["bundle_ref"] = str(root.resolve().relative_to(repo_root.resolve()))
            _transition(st, "acquired_raw", st["bundle_ref"])
            _save(workdir, st)
        bundle = validate_bundle(resolve_stored_bundle(st["bundle_ref"], repo_root, data_dir))
        if st["state"] == "created":
            _transition(st, "acquired_raw", f"imported {st['bundle_ref']}")
        if should_cancel():
            raise Cancelled("processing cancelled")
        res = proc_mod.process_bundle(
            bundle,
            workdir / "processed",
            repo_root,
            progress,
            cache_only=inference_cache_only,
        )
    except Cancelled:
        _transition(st, "cancelled")
        _save(workdir, st)
        raise
    except Exception as exc:
        _transition(st, "failed", str(exc)[:500])
        _save(workdir, st)
        raise
    canals = read_json(workdir / "processed" / "canals.geojson")
    aoi = Aoi.from_geojson(st["aoi"])
    parent = proc_mod.choose_parent_canal(canals, aoi, st.get("parent_canal_feature_id"))
    st["parent_canal_feature_id"] = parent["id"]
    out: dict[str, Any] = {
        "fields_raw_ref": "processed/fields_raw.geojson",
        "fields_ref": "processed/fields_proposed.geojson",
        "canals_ref": "processed/canals.geojson",
        "imagery": res.imagery,
        "weather": res.weather,
        "terrain": res.terrain,
        "inference": res.inference,
        "parent_canal_feature_id": parent["id"],
        "warnings": res.warnings,
        "blockers": list(res.blockers),
        "cache_hits": res.cache_hits,
    }
    if res.inference.get("state") != "done":
        _transition(st, "awaiting_inference", res.inference.get("command", ""))
        out.update(
            state="awaiting_inference",
            inference_command=res.inference.get("command"),
            review_items=[],
        )
        _save(workdir, st)
        return out
    _transition(st, "processed", f"{res.inference['raw_polygons']} raw polygons")
    try:
        r = _run_review(workdir, st, [], reviewer=None)
    except ValueError as exc:
        out["blockers"].append(str(exc))
        _transition(st, "needs_review", str(exc))
        st["review_started_at"] = iso(utc_now())
        out.update(state="needs_review", review_items=[])
        _save(workdir, st)
        return out
    _transition(st, "needs_review", f"{r['review'].summary['selected']} proposed fields")
    st["review_started_at"] = iso(utc_now())
    _save(workdir, st)
    out.update(
        state="needs_review",
        review_items=_review_items(r["review"]),
        review_summary=r["review"].summary,
    )
    return out


def _known_model_ids(workdir: Path) -> set[str]:
    raw_path = Path(workdir) / "processed" / "fields_raw.geojson"
    if not raw_path.is_file():
        raise ReviewRejected("processed fields are not available")
    raw = read_json(raw_path)
    return {
        str(feature.get("id") or feature["properties"]["model_id"]) for feature in raw["features"]
    }


def _canal_ids(workdir: Path) -> set[str]:
    path = Path(workdir) / "processed" / "canals.geojson"
    if not path.is_file():
        raise ReviewRejected("processed canals are not available")
    canals = read_json(path)
    return {str(feature["id"]) for feature in canals.get("features", []) if feature.get("id")}


def apply_review(workdir: Path, edits: dict, expected_version: int) -> dict:
    """Apply reviewer edits (version-checked) and mark the intake reviewed.

    A stale ``expected_version`` raises ``VersionConflict`` and does not write.
    Rejected field or network input raises ``ReviewRejected`` and also leaves
    the version unchanged. A selection that cannot yield 30 fields stays in
    ``needs_review`` with structural blockers.
    """
    workdir = Path(workdir)
    st = _load(workdir)
    if st["state"] not in ("needs_review", "reviewed"):
        raise StageError(f"cannot review in state {st['state']}")
    if expected_version != st["review_version"]:
        raise VersionConflict(
            f"review version {st['review_version']} != expected {expected_version}"
        )
    raw_edits = list(edits.get("field_edits") or [])
    me = field_edits(raw_edits, _known_model_ids(workdir) if raw_edits else set())
    cfg = dict(edits.get("review_config") or {})
    raw_network = edits.get("network", cfg.get("network"))
    cfg.pop("network", None)
    if raw_network is not None:
        st["network_review"] = network_review(raw_network, _canal_ids(workdir))
        st["parent_canal_feature_id"] = st["network_review"]["source_feature_id"]
    if "parent_canal_feature_id" in edits:
        parent = edits["parent_canal_feature_id"]
        if parent not in _canal_ids(workdir):
            raise ReviewRejected(f"parent canal {parent} is not an observed canal in this intake")
        st["parent_canal_feature_id"] = parent
    if "review_config" in edits:
        st["review_config"] = cfg
    reviewer = edits.get("reviewer")
    blockers: list[str] = []
    warnings: list[str] = []
    summary = None
    try:
        r = _run_review(workdir, st, me, reviewer)
        summary = r["review"].summary
        if summary["selected"] != 30:
            warnings.append("selection is not 30 fields")
    except ReviewRejected:
        raise
    except ValueError as exc:
        blockers.append(str(exc))
    st["review_blockers"] = blockers
    if summary is not None:
        st["review_summary"] = summary
    st["review_version"] += 1
    (workdir / "review").mkdir(exist_ok=True)
    write_json(
        workdir / "review" / f"edits_v{st['review_version']}.json",
        {**edits, "applied_at": iso(utc_now())},
    )
    if blockers:
        _transition(st, "needs_review", f"v{st['review_version']} blocked")
    else:
        _transition(st, "reviewed", f"v{st['review_version']} by {reviewer}")
    _save(workdir, st)
    return {
        "version": st["review_version"],
        "blockers": blockers,
        "warnings": warnings,
        "network_reviewed": bool((st.get("network_review") or {}).get("acknowledged")),
        "review_summary": summary,
    }


def update_index(data_dir: Path, pilot_id: str, pilot_version: str, name: str) -> Path:
    idx_p = Path(data_dir) / "pilots" / "index.json"
    idx = read_json(idx_p) if idx_p.exists() else []
    idx = [
        e for e in idx if not (e["pilot_id"] == pilot_id and e["pilot_version"] == pilot_version)
    ]
    idx.append(
        {
            "pilot_id": pilot_id,
            "pilot_version": pilot_version,
            "name": name,
            "published_at": iso(utc_now()),
        }
    )
    idx.sort(key=lambda e: (e["pilot_id"], e["pilot_version"]))
    return write_json(idx_p, idx)


def _build_validated_stage(
    workdir: Path,
    stage: Path,
    st: dict,
    pilot_id: str,
    pilot_version: str,
    repo_root: Path,
    created_at: datetime | None,
    warabandi: str = "declared_cca",
    source_capacity_m3_s: float | None = None,
) -> None:
    """Write one validated package into an empty staging directory."""
    rs = read_json(workdir / "review" / "state.json")
    bundle = validate_bundle(repo_root / st["bundle_ref"])
    fields = [ReviewedField(**f) for f in rs["fields"]]
    build_package(
        stage_dir=stage,
        processed=workdir / "processed",
        bundle_manifest=bundle.manifest,
        bundle_ref=st["bundle_ref"],
        aoi=Aoi.from_geojson(st["aoi"]),
        pilot_id=pilot_id,
        pilot_version=pilot_version,
        name=st.get("name") or pilot_id,
        geographic_name_basis=st.get("geographic_name_basis") or "user-supplied AOI",
        fields=fields,
        review_state=rs,
        parent_canal_id=st["parent_canal_feature_id"],
        created_at=created_at,
        warabandi=warabandi,
        source_capacity_m3_s=source_capacity_m3_s,
    )
    errors = validate_package(stage)
    if errors:
        raise PackageValidationError(errors)


def _package_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): file_sha256(p) for p in root.rglob("*") if p.is_file()}


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value)


def publish(
    workdir: Path,
    pilot_id: str,
    pilot_version: str,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> PilotManifest:
    """Build, validate (→ validated) and publish an immutable pilot version (→ published)."""
    workdir = Path(workdir)
    repo_root = Path(repo_root or config.ROOT)
    data_dir = Path(data_dir or config.DATA_DIR)
    st = _load(workdir)
    if st["state"] not in ("reviewed", "validated"):
        raise StageError(f"cannot publish from state {st['state']} (review first)")
    blockers = structural_blockers(st)
    if blockers:
        raise StructuralBlock(blockers)
    if st.get("pilot_id") and st["pilot_id"] != pilot_id:
        raise StageError(f"intake belongs to {st['pilot_id']}, not {pilot_id}")
    final = data_dir / "pilots" / pilot_id / pilot_version
    if final.exists():
        raise FileExistsError(f"{final} already published (immutable)")
    network = st.get("network_review") or {}
    stage = final.with_name(pilot_version + ".partial")
    if stage.exists():
        shutil.rmtree(stage)
    try:
        _build_validated_stage(
            workdir,
            stage,
            st,
            pilot_id,
            pilot_version,
            repo_root,
            created_at=None,
            warabandi=network.get("roster_basis") or "declared_cca",
            source_capacity_m3_s=network.get("capacity_m3_s"),
        )
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    _transition(st, "validated", "package validators passed")
    _save(workdir, st)
    stage.rename(final)
    update_index(data_dir, pilot_id, pilot_version, st.get("name") or pilot_id)
    readiness = write_readiness(data_dir, pilot_id, pilot_version)
    _transition(st, "published", str(final.relative_to(data_dir.parent)))
    st["published_ref"] = str(final.relative_to(data_dir.parent))
    st["library_readiness"] = readiness
    _save(workdir, st)
    return PilotManifest.model_validate(json.loads((final / "manifest.json").read_text()))


def reproduce_published(
    workdir: Path,
    pilot_id: str,
    pilot_version: str,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
) -> tuple[PilotManifest, bool]:
    """Rebuild a published package and confirm every file hash.

    The published clock (``pilot.json`` ``created_at``) is reused so a second run is
    byte-stable. Pilot-b matches the declared 120 ha warabandi. Pilot-a matches the
    earlier selected-area rule. A mismatch of both raises ``ReproductionError`` and
    leaves the published directory untouched.
    """
    workdir = Path(workdir)
    repo_root = Path(repo_root or config.ROOT)
    data_dir = Path(data_dir or config.DATA_DIR)
    st = _load(workdir)
    if st["state"] != "published":
        raise StageError(f"cannot reproduce from state {st['state']}")
    if st.get("pilot_id") and st["pilot_id"] != pilot_id:
        raise StageError(f"intake belongs to {st['pilot_id']}, not {pilot_id}")
    final = data_dir / "pilots" / pilot_id / pilot_version
    if not final.is_dir():
        raise StageError(f"published package missing: {final}")
    created_at = _parse_utc(read_json(final / "pilot.json")["created_at"])
    published = _package_hashes(final)
    differed: list[str] = []
    for warabandi in ("declared_cca", "selected_area"):
        stage = final.with_name(pilot_version + ".partial")
        if stage.exists():
            shutil.rmtree(stage)
        try:
            _build_validated_stage(
                workdir,
                stage,
                st,
                pilot_id,
                pilot_version,
                repo_root,
                created_at=created_at,
                warabandi=warabandi,
            )
            rebuilt = _package_hashes(stage)
            matched = rebuilt == published
            if not matched:
                differed = sorted(
                    k for k in set(rebuilt) | set(published) if rebuilt.get(k) != published.get(k)
                )
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        shutil.rmtree(stage)
        if matched:
            return (
                PilotManifest.model_validate(json.loads((final / "manifest.json").read_text())),
                False,
            )
    raise ReproductionError(
        f"{pilot_id}/{pilot_version} does not match the declared-CCA or selected-area "
        f"builder; the published version is immutable and was left unchanged. "
        f"Differing files: {', '.join(differed[:8])}"
    )


def status(workdir: Path) -> dict:
    return _load(workdir)
