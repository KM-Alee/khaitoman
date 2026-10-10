"""AT01: published pilot-a and pilot-b packages, not fixtures.

Reads ``data/pilots/<pilot>/reviewed-v1`` and the seeded raw bundles. Rejection
cases copy a package under tmp and never weaken the published-package assertions.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.schemas import Edge, Node
from aabflow.ingestion.imagery.delineate import CHECKPOINT_ID, UPSTREAM_COMMIT
from aabflow.ingestion.onboarding import pipeline
from aabflow.ingestion.packages.bundle import validate_bundle
from aabflow.ingestion.packages.validate import check_graph, validate_package

ROOT = Path(__file__).resolve().parents[2]
PILOTS = ("pilot-a", "pilot-b")
VERSION = "reviewed-v1"
SCENE_ID = re.compile(r"^S2[A-D]_[0-9]{2}[A-Z]{3}_[0-9]{8}_[0-9]+_L2A$")
FLAG_KEYS = (
    "geography_reviewed",
    "topology_structurally_valid",
    "rights_verification",
    "cost_evidence",
    "crop_calibration",
)
BUNDLES = {
    "pilot-a": (
        "data/raw/bundles/pilot-a/20261010T003625Z-48408f71",
        "9472bc45757d3708439089be35e06c9fffade965117f5535c62e8eb806edb317",
    ),
    "pilot-b": (
        "data/raw/bundles/pilot-b/20261010T003841Z-798d10d2",
        "5111cb539e9ce939d322e22831d70155e986492f641ec91427a0acfe913dbf2a",
    ),
}


def _published(pilot: str) -> Path:
    path = ROOT / "data" / "pilots" / pilot / VERSION
    assert path.is_dir(), path
    assert "fixtures" not in path.parts
    return path


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ancestors(node: str, parent: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    while node in parent and node not in seen:
        seen.add(node)
        node = parent[node]
        out.append(node)
    return out


def _rewrite_listed(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.write_text(text, encoding="utf-8")
    manifest = _load(root / "manifest.json")
    digest = file_sha256(path)
    size = path.stat().st_size
    matched = False
    for entry in manifest["files"]:
        if entry["path"] == rel:
            entry["sha256"] = digest
            entry["size_bytes"] = size
            matched = True
    assert matched, rel
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def test_AT01_published_packages_have_real_scene_ids_fields_and_graph():
    """Both reviewed pilots: real scene/source IDs, 30 fields, directed tree, hashes."""
    seen_scenes: list[set[str]] = []
    seen_bboxes: list[list] = []
    flag_paths: list[Path] = []
    for pilot in PILOTS:
        root = _published(pilot)
        errors = validate_package(root)
        assert errors == [], errors
        pilot_doc = _load(root / "pilot.json")
        manifest = _load(root / "manifest.json")
        assert pilot_doc["pilot_id"] == pilot
        assert pilot_doc["pilot_version"] == VERSION
        assert pilot_doc["pilot_id"] != "fixture-a"

        listed = {entry["path"]: entry for entry in manifest["files"]}
        on_disk = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
        assert "manifest.json" not in listed
        for rel, entry in listed.items():
            assert file_sha256(on_disk[rel]) == entry["sha256"], rel
            assert on_disk[rel].stat().st_size == entry["size_bytes"], rel
        extra = set(on_disk) - set(listed) - {"manifest.json"}
        assert extra == set()
        hashed = sorted(
            (rel, file_sha256(path))
            for rel, path in on_disk.items()
            if rel not in {"pilot.json", "manifest.json"}
        )
        assert pilot_doc["package_sha256"] == content_hash(hashed)

        scenes = [im["scene_id"] for im in pilot_doc["imagery"]]
        assert len(scenes) >= 2
        assert all(SCENE_ID.fullmatch(s) for s in scenes)
        assert "S2-TEST" not in scenes
        for scene in scenes:
            assert (root / "imagery" / f"{scene}.json").is_file()
            assert f"s2:{scene}" in manifest["source_ids"]
            assert f"ev:s2:{scene}" in pilot_doc["source_refs"]
        seen_scenes.append(set(scenes))
        seen_bboxes.append(pilot_doc["aoi_bbox"])

        ids = manifest["source_ids"]
        assert any(re.fullmatch(r"osm:way/[0-9]+", i) for i in ids)
        assert any(i.startswith("grain:") and len(i) > len("grain:") for i in ids)
        assert any(i.startswith("weather:") for i in ids)
        assert any(i.startswith("delineate:") and len(i) > len("delineate:") for i in ids)
        assert any(i.startswith(f"bundle:{pilot}/") for i in ids)

        fields = _load(root / "fields.geojson")["features"]
        assert len(fields) == 30
        assert len({f["id"] for f in fields}) == 30

        nodes = [Node.model_validate(n) for n in _load(root / "network.json")["nodes"]]
        edges = [Edge.model_validate(e) for e in _load(root / "network.json")["edges"]]
        graph_errors: list[str] = []
        parent = check_graph(nodes, edges, graph_errors)
        assert graph_errors == [], graph_errors
        roster = _load(root / "roster.json")["seasons"]
        heads = {w["outlet_node_id"] for wins in roster.values() for w in wins}
        assert len(heads) >= 2
        for head in heads:
            below = [e for e in edges if head in _ancestors(e.downstream_node_id, parent)]
            assert len(below) >= 2, head
            assert len({e.delivery_factor for e in below}) >= 2, head

        flags = pilot_doc["review_flags"]
        assert tuple(flags) == FLAG_KEYS
        assert "verified" not in flags
        assert flags["geography_reviewed"] is True
        assert flags["topology_structurally_valid"] is True
        assert flags["rights_verification"] == "assumed"
        assert flags["cost_evidence"] == "assumed"
        assert flags["crop_calibration"] == "uncalibrated"
        flag_paths.append(root / "pilot.json")

        versions = manifest["processing_versions"]
        assert versions["delineate_checkpoint"] == CHECKPOINT_ID
        assert versions["delineate_upstream_commit"] == UPSTREAM_COMMIT
        assert versions["network_template"] == "two-watercourse-three-reach-v1"
        evidence = _load(root / "evidence.json")
        delineate = next(e for e in evidence if e["evidence_id"] == "ev:delineate")
        assert "cache_hit=" in delineate["transformation"]
        assert re.search(r"checkpoint sha256 [0-9a-f]{64}", delineate["method_version"])
        assert delineate["source_asset_id"] == CHECKPOINT_ID
        assert delineate["evidence_id"] in pilot_doc["source_refs"]
        for ref in pilot_doc["source_refs"]:
            assert any(e["evidence_id"] == ref for e in evidence)

        assert pilot_doc["bundle_ref"] == BUNDLES[pilot][0]
        summary = _load(root / "review_log.json")["summary"]
        assert summary["selected"] == 30
        assert isinstance(summary["selected_corrected"], int)
        assert summary["review_started_at"] <= summary["review_finished_at"]

    assert seen_scenes[0] != seen_scenes[1]
    assert seen_bboxes[0] != seen_bboxes[1]
    assert flag_paths[0] != flag_paths[1]


def test_AT01_raw_bundle_matches_published_ref():
    """Byte-check the ignored raw bundles when this checkout has them."""
    missing = [
        rel for rel, _sha in BUNDLES.values() if not (ROOT / rel / "bundle_manifest.json").is_file()
    ]
    if missing:
        pytest.skip("ignored raw bundles are not in this checkout: " + ", ".join(missing))
    for pilot, (rel, digest) in BUNDLES.items():
        root = _published(pilot)
        bundle_root = ROOT / rel
        assert file_sha256(bundle_root / "bundle_manifest.json") == digest
        bundle = validate_bundle(bundle_root)
        assert bundle.manifest["pilot_id"] == pilot
        assert _load(root / "pilot.json")["bundle_ref"] == rel


def test_reproduce_mismatch_leaves_published_tree(tmp_path, monkeypatch):
    """A builder mismatch must not replace or delete the published version."""
    published = tmp_path / "data" / "pilots" / "pilot-a" / "reviewed-v1"
    shutil.copytree(_published("pilot-a"), published)
    before = {
        path.relative_to(published).as_posix(): file_sha256(path)
        for path in published.rglob("*")
        if path.is_file()
    }
    workdir = tmp_path / "intake"
    workdir.mkdir()
    (workdir / "intake.json").write_text(
        json.dumps({"state": "published", "pilot_id": "pilot-a"}),
        encoding="utf-8",
    )

    def fake_build(_workdir, stage, *_args, **_kwargs):
        stage.mkdir(parents=True)
        (stage / "changed.txt").write_text("not the published package", encoding="utf-8")

    monkeypatch.setattr(pipeline, "_build_validated_stage", fake_build)
    with pytest.raises(pipeline.ReproductionError):
        pipeline.reproduce_published(
            workdir,
            "pilot-a",
            "reviewed-v1",
            data_dir=tmp_path / "data",
            repo_root=tmp_path,
        )
    after = {
        path.relative_to(published).as_posix(): file_sha256(path)
        for path in published.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (published.parent / "reviewed-v1.partial").exists()
    assert not (published.parent / "reviewed-v1.previous").exists()


def _copy_package(tmp_path: Path) -> Path:
    dest = tmp_path / "pkg"
    shutil.copytree(_published("pilot-a"), dest)
    assert validate_package(dest) == []
    return dest


def test_AT01_rejects_manifest_hash_mismatch(tmp_path):
    root = _copy_package(tmp_path)
    path = root / "aoi.geojson"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    errors = validate_package(root)
    assert any("sha256 mismatch" in e and "aoi.geojson" in e for e in errors), errors


def test_AT01_rejects_invalid_graph(tmp_path):
    root = _copy_package(tmp_path)
    network = _load(root / "network.json")
    extra = json.loads(json.dumps(network["edges"][0]))
    extra["edge_id"] = extra["edge_id"] + "-not-a-tree"
    extra["downstream_node_id"] = network["edges"][1]["downstream_node_id"]
    network["edges"].append(extra)
    _rewrite_listed(root, "network.json", json.dumps(network, indent=2) + "\n")
    errors = validate_package(root)
    assert any("not a tree" in e for e in errors), errors
    assert not any("sha256 mismatch" in e for e in errors), errors


def test_AT01_rejects_missing_scene_id(tmp_path):
    blank = _copy_package(tmp_path)
    pilot = _load(blank / "pilot.json")
    pilot["imagery"][0]["scene_id"] = ""
    _rewrite_listed(blank, "pilot.json", json.dumps(pilot, indent=2) + "\n")
    errors = validate_package(blank)
    assert any("missing scene id" in e for e in errors), errors
    assert not any("sha256 mismatch" in e for e in errors), errors

    absent_dir = tmp_path / "absent"
    absent_dir.mkdir()
    absent = _copy_package(absent_dir)
    pilot = _load(absent / "pilot.json")
    del pilot["imagery"][0]["scene_id"]
    _rewrite_listed(absent, "pilot.json", json.dumps(pilot, indent=2) + "\n")
    errors = validate_package(absent)
    assert any("pilot.json invalid" in e or "missing scene id" in e for e in errors), errors


def test_AT01_rejects_under_30_reviewed_fields(tmp_path):
    root = _copy_package(tmp_path)
    fields = _load(root / "fields.geojson")
    assert len(fields["features"]) == 30
    fields["features"].pop()
    _rewrite_listed(root, "fields.geojson", json.dumps(fields, indent=2) + "\n")
    errors = validate_package(root)
    assert any("exactly 30" in e for e in errors), errors
    assert not any("sha256 mismatch" in e and "fields.geojson" in e for e in errors), errors
