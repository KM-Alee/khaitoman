"""Onboarding pipeline as callable stages (PRD §5.3, T2.6, F03/AT16).

``acquired_raw → processed → needs_review → reviewed → validated → published``

A *workdir* holds one intake::

    <workdir>/intake.json      state, AOI, source mode, bundle ref, history, review version
    <workdir>/processed/       processed sources + raw Delineate output (process.py)
    <workdir>/review/          review_log.json, state.json, edits_v<N>.json

Entry points used by the API (POST /onboarding …) and the CLI scripts:
``validate_aoi``, ``create_intake``, ``process``, ``apply_review``, ``publish``.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from shapely.geometry import shape

from aabflow import config
from aabflow.domain.schemas import PilotManifest

from ..aoi import MAX_AOI_AREA_M2, Aoi, AoiError
from ..common import IngestionError, iso, read_json, utc_now, write_json
from ..packages.builder import ReviewedField, build_package
from ..packages.bundle import validate_bundle
from ..packages.validate import PackageValidationError, validate_package
from ..review.fields import ManualEdit, ReviewConfig, review, selected_wgs84
from . import process as proc_mod
from .acquire import AcquisitionConfig, Cancelled, acquire_bundle

Progress = Callable[[str, float | None, str], None]
SourceMode = Literal["online", "raw_package"]
CANAL_EXCLUSION_M = 8.0


class VersionConflict(ValueError):
    pass


class StageError(IngestionError):
    pass


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
        root = (Path(repo_root or config.ROOT) / raw_package_ref).resolve()
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
        bundle = validate_bundle(repo_root / st["bundle_ref"])
        if st["state"] == "created":
            _transition(st, "acquired_raw", f"imported {st['bundle_ref']}")
        if should_cancel():
            raise Cancelled("processing cancelled")
        res = proc_mod.process_bundle(bundle, workdir / "processed", repo_root, progress)
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


def apply_review(workdir: Path, edits: dict, expected_version: int) -> dict:
    """Apply reviewer edits (version-checked) and mark the intake reviewed."""
    workdir = Path(workdir)
    st = _load(workdir)
    if st["state"] not in ("needs_review", "reviewed"):
        raise StageError(f"cannot review in state {st['state']}")
    if expected_version != st["review_version"]:
        raise VersionConflict(
            f"review version {st['review_version']} != expected {expected_version}"
        )
    me = [ManualEdit(**e) for e in edits.get("field_edits", [])]
    if "parent_canal_feature_id" in edits:
        st["parent_canal_feature_id"] = edits["parent_canal_feature_id"]
    if "review_config" in edits:
        st["review_config"] = edits["review_config"]
    reviewer = edits.get("reviewer")
    blockers: list[str] = []
    try:
        r = _run_review(workdir, st, me, reviewer)
        warnings = [] if r["review"].summary["selected"] == 30 else ["selection is not 30 fields"]
    except ValueError as exc:
        blockers.append(str(exc))
        warnings = []
    st["review_version"] += 1
    write_json(
        workdir / "review" / f"edits_v{st['review_version']}.json",
        {**edits, "applied_at": iso(utc_now())},
    )
    if not blockers:
        _transition(st, "reviewed", f"v{st['review_version']} by {reviewer}")
    _save(workdir, st)
    return {"version": st["review_version"], "blockers": blockers, "warnings": warnings}


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
    if st.get("pilot_id") and st["pilot_id"] != pilot_id:
        raise StageError(f"intake belongs to {st['pilot_id']}, not {pilot_id}")
    final = data_dir / "pilots" / pilot_id / pilot_version
    if final.exists():
        raise FileExistsError(f"{final} already published (immutable)")
    rs = read_json(workdir / "review" / "state.json")
    bundle = validate_bundle(repo_root / st["bundle_ref"])
    stage = final.with_name(pilot_version + ".partial")
    if stage.exists():
        shutil.rmtree(stage)
    fields = [ReviewedField(**f) for f in rs["fields"]]
    try:
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
        )
        errors = validate_package(stage)
        if errors:
            raise PackageValidationError(errors)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    _transition(st, "validated", "package validators passed")
    _save(workdir, st)
    stage.rename(final)
    update_index(data_dir, pilot_id, pilot_version, st.get("name") or pilot_id)
    _transition(st, "published", str(final.relative_to(data_dir.parent)))
    st["published_ref"] = str(final.relative_to(data_dir.parent))
    _save(workdir, st)
    return PilotManifest.model_validate(json.loads((final / "manifest.json").read_text()))


def status(workdir: Path) -> dict:
    return _load(workdir)
