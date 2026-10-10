"""Delineate runner keys/collection, GRAIN reader, manifest validator and onboarding stage guards.

Synthetic test fixtures only (no network, no vision container).
"""

from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from aabflow.domain.hashes import file_sha256
from aabflow.ingestion.aoi import AoiError
from aabflow.ingestion.grain import reader as grain
from aabflow.ingestion.imagery import delineate
from aabflow.ingestion.onboarding import pipeline
from aabflow.ingestion.packages.validate import check_fields, check_manifest

AOI_GJ = {"type": "Polygon", "coordinates": [[[72.306, 30.776], [72.33, 30.776], [72.33, 30.798],
                                             [72.306, 30.798], [72.306, 30.776]]]}  # fmt: skip


def _repo(tmp_path):
    (tmp_path / "vision" / "configs").mkdir(parents=True)
    (tmp_path / "vision" / delineate.BASE_CONFIG).write_text("model: [x]\n")
    tif = tmp_path / "in.tif"
    tif.write_bytes(b"synthetic raster bytes")
    return tmp_path, tif


def test_inference_key_depends_on_input_and_config(tmp_path):
    repo, tif = _repo(tmp_path)
    k1 = delineate.inference_key(tif, repo)
    assert k1 == delineate.inference_key(tif, repo)
    (repo / "vision" / delineate.BASE_CONFIG).write_text("model: [y]\n")
    assert delineate.inference_key(tif, repo) != k1


def test_prepare_writes_upstream_batch_and_pending_without_docker(tmp_path, monkeypatch):
    repo, tif = _repo(tmp_path)
    job = delineate.prepare(tif, repo)
    batch = json.loads(job.batch_yaml.read_text().split("\n", 1)[1])
    assert batch["base_config"].endswith(delineate.BASE_CONFIG)
    assert batch["data_root"] == f"/app/vision/runs/{job.key}/input"
    assert batch["include"] == ["scene"]
    assert "run_batch.py" in job.command_str() and "compose.vision.yaml" in job.command_str()
    monkeypatch.setattr(delineate, "docker_available", lambda: False)
    with pytest.raises(delineate.InferencePending):
        delineate.run(job)


def test_staged_input_guard(tmp_path):
    repo, tif = _repo(tmp_path)
    job = delineate.prepare(tif, repo)
    job.input_tif.write_bytes(b"tampered")
    with pytest.raises(Exception, match="differs"):
        delineate.prepare(tif, repo)


def test_collect_keeps_model_ids(tmp_path):
    repo, tif = _repo(tmp_path)
    job = delineate.prepare(tif, repo)
    job.output_gpkg.parent.mkdir(parents=True)
    g = gpd.GeoDataFrame({"area": [1.0, 2.0]}, geometry=[box(300000, 3400000, 300100, 3400100),
                         box(300200, 3400000, 300300, 3400100)], crs="EPSG:32643")  # fmt: skip
    g.to_file(job.output_gpkg, layer="fields", driver="GPKG")
    (job.run_dir / "run.json").write_text(json.dumps({"ok": True}))
    assert job.done()
    fc = delineate.collect(job)
    ids = [f["id"] for f in fc["features"]]
    assert len(ids) == 2 and all(i.startswith(f"da:{job.key}:") for i in ids)
    assert fc["properties"]["source_crs"] == "EPSG:32643"
    assert fc["properties"]["gpkg_sha256"] == file_sha256(job.output_gpkg)


def test_grain_reader_schema_and_subset(tmp_path):
    p = tmp_path / "g.parquet"
    gpd.GeoDataFrame(
        {"GRAIN_ID": [1, 2], "use": ["Agricultural", "Agricultural"]},
        geometry=[
            LineString([(72.31, 30.78), (72.32, 30.79)]),
            LineString([(70, 25), (70.1, 25.1)]),
        ],
        crs="EPSG:4326",
    ).to_parquet(p)
    sub = grain.read_subset(p, (72.3, 30.77, 72.33, 30.80))
    assert list(sub["GRAIN_ID"]) == [1]
    s = grain.schema_summary(sub)
    assert s["categorical_values"]["use"] == ["Agricultural"]
    assert grain.id_column(sub) == "GRAIN_ID"
    with pytest.raises(Exception, match="identifier"):
        grain.id_column(sub.drop(columns=["GRAIN_ID"]))


def test_validate_aoi_limits():
    v = pipeline.validate_aoi(AOI_GJ)
    assert v["metric_crs"] == "EPSG:32643" and not v["blockers"] and 5e6 < v["area_m2"] < 6e6
    big = {
        "type": "Polygon",
        "coordinates": [[[72.0, 30.5], [72.2, 30.5], [72.2, 30.7], [72.0, 30.7], [72.0, 30.5]]],
    }
    assert pipeline.validate_aoi(big)["blockers"]


def test_create_intake_guards(tmp_path):
    big = {
        "type": "Polygon",
        "coordinates": [[[72.0, 30.5], [72.2, 30.5], [72.2, 30.7], [72.0, 30.7], [72.0, 30.5]]],
    }
    with pytest.raises(AoiError):
        pipeline.create_intake("i1", big, "online", None, tmp_path / "w1")
    with pytest.raises(ValueError, match="raw_package_ref"):
        pipeline.create_intake("i2", AOI_GJ, "raw_package", None, tmp_path / "w2")
    with pytest.raises(ValueError, match="source_mode"):
        pipeline.create_intake("i3", AOI_GJ, "ftp", None, tmp_path / "w3")  # type: ignore[arg-type]
    st = pipeline.create_intake("i4", AOI_GJ, "online", None, tmp_path / "w4", pilot_id="pilot-x")
    assert st["state"] == "created" and st["review_version"] == 0
    with pytest.raises(pipeline.StageError):
        pipeline.create_intake("i4", AOI_GJ, "online", None, tmp_path / "w4")
    with pytest.raises(pipeline.StageError, match="cannot review"):
        pipeline.apply_review(tmp_path / "w4", {}, 0)
    with pytest.raises(pipeline.StageError, match="cannot publish"):
        pipeline.publish(tmp_path / "w4", "pilot-x", "v1", data_dir=tmp_path / "data")
    st["state"] = "needs_review"
    (tmp_path / "w4" / "intake.json").write_text(json.dumps(st))
    with pytest.raises(pipeline.VersionConflict):
        pipeline.apply_review(tmp_path / "w4", {}, 5)


def _manifest_pkg(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "a.json").write_text("{}")
    m = {"manifest_version": "1", "pilot_id": "p", "pilot_version": "v", "state": "published",
         "files": [{"path": "a.json", "size_bytes": 2, "sha256": file_sha256(root / "a.json"), "kind": "x"}],
         "source_ids": [], "licenses": [], "processing_versions": {}, "generated_at": "2026-10-10T00:00:00Z"}  # fmt: skip
    (root / "manifest.json").write_text(json.dumps(m))
    return root, m


def test_manifest_checks(tmp_path):
    root, m = _manifest_pkg(tmp_path)
    errs: list[str] = []
    check_manifest(root, errs)
    assert errs == []
    for mutate, msg in [
        (lambda m: m["files"][0].update(path="../a.json"), "traversal"),
        (lambda m: m["files"][0].update(sha256="0" * 64), "sha256"),
        (lambda m: m["files"].append(dict(m["files"][0])), "duplicate"),
        (lambda m: m["files"][0].update(path="a.sh"), "format"),
        (lambda m: m.update(manifest_version="2"), "invalid"),
    ]:
        mm = json.loads(json.dumps(m))
        mutate(mm)
        (root / "manifest.json").write_text(json.dumps(mm))
        errs = []
        check_manifest(root, errs)
        assert any(msg in e for e in errs), (msg, errs)
    (root / "manifest.json").write_text(json.dumps(m))
    (root / "b.json").write_text("{}")
    errs = []
    check_manifest(root, errs)
    assert any("unlisted" in e for e in errs)


def test_check_fields_count_overlap_and_area():
    from aabflow.ingestion.aoi import Aoi, to_metric, to_wgs84

    aoi = Aoi.from_geojson(AOI_GJ)
    x0, y0 = to_metric(aoi.geometry, aoi.metric_crs).bounds[:2]

    def feat(i, g):
        gw = to_wgs84(g, aoi.metric_crs)
        a = to_metric(gw, aoi.metric_crs).area
        props = {"field_id": f"p:field-{i}", "label": str(i), "geometry_ref": f"p:field-{i}",
                 "gross_area_m2": a, "gross_area_ha": a / 1e4, "soil_profile_id": "s",
                 "outlet_node_id": "n", "group": "head"}  # fmt: skip
        return {
            "type": "Feature",
            "id": f"p:field-{i}",
            "geometry": gw.__geo_interface__,
            "properties": props,
        }

    feats = [feat(i, box(x0 + 100 + 120 * (i % 6), y0 + 100 + 150 * (i // 6), x0 + 200 + 120 * (i % 6),
                         y0 + 220 + 150 * (i // 6))) for i in range(30)]  # fmt: skip
    errs: list[str] = []
    assert len(check_fields(feats, aoi, errs)) == 30 and errs == []
    errs = []
    check_fields(feats[:29], aoi, errs)
    assert any("exactly 30" in e for e in errs)
    over = [*feats[:29], feat(29, box(x0 + 150, y0 + 150, x0 + 260, y0 + 260))]
    errs = []
    check_fields(over, aoi, errs)
    assert any("overlap" in e for e in errs)
    bad_area = json.loads(json.dumps(feats))
    bad_area[0]["properties"]["gross_area_m2"] *= 2
    bad_area[0]["properties"]["gross_area_ha"] *= 2
    errs = []
    check_fields(bad_area, aoi, errs)
    assert any("metric area" in e for e in errs)
