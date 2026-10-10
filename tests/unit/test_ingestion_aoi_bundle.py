"""AOI limits/CRS and raw-bundle import rules (T2.2, T2.6). Synthetic test fixtures only."""

from __future__ import annotations

import json

import pytest
from shapely.geometry import box

from aabflow.ingestion.aoi import Aoi, AoiError, disjoint, utm_crs_for
from aabflow.ingestion.common import ImmutableRawError, RawStore
from aabflow.ingestion.packages.bundle import (
    BundleError,
    BundleWriter,
    safe_relpath,
    validate_bundle,
)
from aabflow.ingestion.pilot_aois import PILOT_A, PILOT_B


def test_utm_zone_and_swapped_axes():
    assert utm_crs_for(72.3, 30.8).to_epsg() == 32643
    with pytest.raises(AoiError):
        utm_crs_for(30.8, 95.0)  # lat/lon swapped -> latitude out of range


def test_area_is_metric_and_limits():
    a = Aoi.from_bbox(72.30, 30.77, 72.32, 30.79)
    # ~1.91 km x 2.22 km; degrees² would be 0.0004
    assert 4.0e6 < a.area_m2 < 4.6e6
    assert a.metric_crs_id == "EPSG:32643"
    a.check_limits()
    big = Aoi.from_bbox(72.0, 30.5, 72.2, 30.7)
    with pytest.raises(AoiError, match="exceeds"):
        big.check_limits()
    with pytest.raises(AoiError):
        Aoi.from_bbox(72.32, 30.77, 72.30, 30.79)


def test_aoi_rejects_multipolygon_and_invalid():
    with pytest.raises(AoiError):
        Aoi.from_geojson({"type": "MultiPolygon", "coordinates": []})
    bow = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    with pytest.raises(AoiError, match="invalid"):
        Aoi.from_geojson(bow)


def test_pilot_aois_disjoint_inside_extent_and_small():
    a, b = Aoi.from_bbox(*PILOT_A.bbox), Aoi.from_bbox(*PILOT_B.bbox)
    assert disjoint(a, b)
    ext = box(72.133333, 30.55, 72.8, 31.033333)
    for p in (a, b):
        assert ext.contains(p.geometry)
        assert 2e6 <= p.area_m2 <= 6e6
    assert "Mungi" not in PILOT_A.name and "Mungi" not in PILOT_B.name


@pytest.mark.parametrize(
    "bad", ["/etc/passwd", "../x.json", "a/../../b.json", "a\\b.json", "", "./a.json", "~/a"]
)
def test_safe_relpath_rejects_traversal(bad):
    with pytest.raises(BundleError):
        safe_relpath(bad)


def test_safe_relpath_accepts_plain():
    assert safe_relpath("sentinel2/S2/red.tif") == "sentinel2/S2/red.tif"


def test_raw_store_is_write_once(tmp_path):
    st = RawStore(tmp_path)
    st.put("x/a.json", b"1")
    st.put("x/a.json", b"1")  # same bytes: no-op
    with pytest.raises(ImmutableRawError):
        st.put("x/a.json", b"2")
    with pytest.raises(ImmutableRawError):
        st.path("../escape")


def _bundle(tmp_path):
    st = RawStore(tmp_path / "raw")
    bw = BundleWriter(st, "pilot-x", "b1")
    aoi = Aoi.from_bbox(72.30, 30.77, 72.32, 30.79).feature_collection()
    bw.add_json("aoi.geojson", aoi, "aoi")
    bw.add_bytes("osm/overpass.json", b'{"elements": []}', "osm_overpass")
    root = bw.finalize(aoi).parent
    return root


def test_bundle_roundtrip_and_staging(tmp_path):
    root = _bundle(tmp_path)
    assert root.name == "b1"
    assert not (root.parent / "b1.partial").exists()
    b = validate_bundle(root)
    assert b.one("osm_overpass")["path"] == "osm/overpass.json"


def test_bundle_abort_removes_partial(tmp_path):
    st = RawStore(tmp_path / "raw")
    bw = BundleWriter(st, "pilot-x", "b2")
    bw.add_bytes("a.json", b"{}", "x")
    assert bw.root.exists()
    bw.abort()
    assert not bw.root.exists()


def test_bundle_rejects_duplicate_path(tmp_path):
    st = RawStore(tmp_path / "raw")
    bw = BundleWriter(st, "pilot-x", "b3")
    bw.add_bytes("a.json", b"{}", "x")
    with pytest.raises(BundleError, match="duplicate"):
        bw.add_bytes("a.json", b"{}", "x")


def _rewrite_manifest(root, fn):
    mp = root / "bundle_manifest.json"
    m = json.loads(mp.read_text())
    fn(m)
    mp.chmod(0o644)
    mp.write_text(json.dumps(m))


@pytest.mark.parametrize(
    ("mutate", "msg"),
    [
        (lambda m: m.update(bundle_version="9"), "bundle_version"),
        (lambda m: m["files"][0].update(path="../aoi.geojson"), "traversal"),
        (lambda m: m["files"][0].update(sha256="0" * 64), "sha256"),
        (lambda m: m["files"][0].update(size_bytes=1), "size"),
        (lambda m: m["files"].append(dict(m["files"][0])), "duplicate"),
        (lambda m: m["files"][0].update(path="aoi.exe"), "format"),
    ],
)
def test_bundle_validation_rejections(tmp_path, mutate, msg):
    root = _bundle(tmp_path)
    _rewrite_manifest(root, mutate)
    with pytest.raises(BundleError, match=msg):
        validate_bundle(root)


def test_bundle_rejects_unlisted_file(tmp_path):
    root = _bundle(tmp_path)
    root.chmod(0o755)
    (root / "extra.json").write_text("{}")
    with pytest.raises(BundleError, match="unlisted"):
        validate_bundle(root)
