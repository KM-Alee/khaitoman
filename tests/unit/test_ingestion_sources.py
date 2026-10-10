"""Source transforms: STAC assets, SCL masking, NDVI, display stretch, Overpass, terrain (T2.1-T2.4).

All inputs here are small synthetic test fixtures built in the test (no network).
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import rasterio
from PIL import Image

from aabflow.ingestion.aoi import Aoi
from aabflow.ingestion.common import IngestionError
from aabflow.ingestion.imagery import display
from aabflow.ingestion.osm import overpass
from aabflow.ingestion.stac import sentinel2 as s2
from aabflow.ingestion.terrain import copdem

COG = "image/tiff; application=geotiff; profile=cloud-optimized"


def _asset(href, gsd, common=None, scale=0.0001, offset=-0.1, dtype="uint16"):
    a = {"href": href, "type": COG, "gsd": gsd,
         "raster:bands": [{"nodata": 0, "data_type": dtype, "spatial_resolution": gsd,
                           "scale": scale, "offset": offset}]}  # fmt: skip
    if common:
        a["eo:bands"] = [{"name": common, "common_name": common}]
    return a


def fixture_item():
    """Synthetic STAC item shaped like Earth Search sentinel-2-l2a (test fixture)."""
    return {
        "id": "S2X_TEST",
        "properties": {"datetime": "2025-02-23T06:00:51Z", "proj:code": "EPSG:32643"},
        "assets": {
            "red": _asset("r.tif", 10),
            "green": _asset("g.tif", 10),
            "blue": _asset("b.tif", 10),
            "nir": _asset("n.tif", 10),
            "nir08": _asset("n8.tif", 20, common="nir08"),
            "scl": _asset("scl.tif", 20, scale=1, offset=0, dtype="uint8"),
            "visual": {"href": "tci.tif", "type": COG, "roles": ["visual"]},
            "red-jp2": {"href": "B04.jp2", "type": "image/jp2"},
        },
    }


def test_resolve_assets_from_metadata():
    a = s2.resolve_assets(fixture_item())
    assert (a.red.key, a.nir.key, a.scl.key) == ("red", "nir", "scl")
    assert a.nir.gsd == 10.0  # 10 m B08, not 20 m nir08
    assert a.red.scale == 0.0001 and a.red.offset == -0.1


def test_resolve_assets_missing_scl_and_no_cogs():
    it = fixture_item()
    del it["assets"]["scl"]
    with pytest.raises(IngestionError, match="SCL"):
        s2.resolve_assets(it)
    it2 = {"id": "x", "assets": {"red": {"href": "a.jp2", "type": "image/jp2"}}}
    with pytest.raises(IngestionError, match="cloud-optimized"):
        s2.resolve_assets(it2)


def test_scl_valid_fraction_and_histogram():
    scl = np.array([[4, 4, 8], [9, 3, 5]], dtype="uint8")
    inside = np.array([[True, True, True], [True, True, False]])
    assert s2.aoi_valid_fraction(scl, inside) == pytest.approx(2 / 5)
    h = s2.scl_histogram(scl, inside)
    assert h["vegetation"] == 2 and h["cloud_high_probability"] == 1
    with pytest.raises(IngestionError):
        s2.aoi_valid_fraction(scl, np.zeros_like(inside))


def test_ndvi_masks_invalid_and_zero_denominator():
    red = np.array([[0.05, 0.0, 0.1]])
    nir = np.array([[0.45, 0.0, 0.3]])
    valid = np.array([[True, True, False]])
    out = s2.ndvi(red, nir, valid)
    assert out[0, 0] == pytest.approx(0.8)
    assert np.isnan(out[0, 1]) and np.isnan(out[0, 2])


def test_offset_consistency_detects_offset_free_dn():
    refs = {b: s2.AssetRef(b, "", 10.0, 0.0001, -0.1, 0, "uint16") for b in ("red", "nir")}
    valid = np.ones((2, 2), bool)
    offset_free = {"red": np.full((2, 2), 300), "nir": np.full((2, 2), 3000)}
    oc = s2.offset_consistency(offset_free, refs, valid)
    assert oc["offset_applied"] is False
    with_offset = {"red": np.full((2, 2), 1300), "nir": np.full((2, 2), 4000)}
    assert s2.offset_consistency(with_offset, refs, valid)["offset_applied"] is True
    assert s2.with_offset(refs["red"], False).offset == 0.0


def test_grid_is_pixel_aligned_and_covers_aoi():
    aoi = Aoi.from_bbox(72.306, 30.776, 72.330, 30.798)
    g = s2.grid_for(aoi, "EPSG:32643", buffer_m=600)
    assert g.transform.a == 10 and g.transform.e == -10
    assert g.bounds[0] % 10 == 0 and g.bounds[3] % 10 == 0
    m = s2.aoi_mask(aoi, g)
    assert m.sum() * 100 == pytest.approx(aoi.area_m2, rel=0.02)
    assert not m[0].any() and not m[:, 0].any()  # buffer around the AOI


def test_write_and_read_local_window(tmp_path):
    aoi = Aoi.from_bbox(72.306, 30.776, 72.310, 30.780)
    g = s2.grid_for(aoi, "EPSG:32643", buffer_m=0)
    arr = np.arange(g.width * g.height, dtype="uint16").reshape(g.height, g.width)
    p = s2.write_geotiff(tmp_path / "red.tif", [arr], g, 0, ["red"])
    back, meta = s2.read_window(str(p), g, categorical=False)
    assert np.array_equal(back, arr)
    assert meta["resampling"].startswith("none")


def test_display_stretch_corners_and_webp():
    rng = np.random.default_rng(0)
    rgb = rng.uniform(0.02, 0.3, size=(3, 40, 50))
    valid = np.ones((40, 50), bool)
    valid[:5, :5] = False
    p = display.stretch_params(rgb, valid)
    assert p["stretch_id"] == display.STRETCH_ID and p["low_reflectance"] < p["high_reflectance"]
    tf = rasterio.Affine(10, 0, 300000, 0, -10, 3410000)
    img = display.render_display(rgb, valid, "EPSG:32643", tf)
    (w, n), (e, n2), (e2, s), (w2, s2_) = img.corners_wgs84
    assert n == n2 and e == e2 and w == w2 and s == s2_ and w < e and s < n  # north-up TL,TR,BR,BL
    im = Image.open(io.BytesIO(img.webp))
    assert im.format == "WEBP" and im.mode == "RGBA"
    with pytest.raises(ValueError):
        display.stretch_params(rgb, np.zeros_like(valid))


def test_overpass_query_and_features():
    q = overpass.build_query((72.3, 30.7, 72.4, 30.8))
    assert "(30.700000,72.300000,30.800000,72.400000)" in q  # south,west,north,east
    assert "canal|ditch|drain" in q and "out geom tags" in q
    with pytest.raises(IngestionError):
        overpass.build_query((72.4, 30.7, 72.3, 30.8))
    payload = {"elements": [
        {"type": "way", "id": 5, "tags": {"waterway": "canal", "name": "R-1"},
         "geometry": [{"lon": 72.3, "lat": 30.7}, {"lon": 72.31, "lat": 30.71}]},
        {"type": "node", "id": 1},
        {"type": "way", "id": 6, "tags": {"waterway": "ditch"}, "geometry": [{"lon": 1, "lat": 1}]},
    ]}  # fmt: skip
    f = overpass.to_features(payload)
    assert [x["id"] for x in f] == ["osm:way/5"]
    assert f[0]["properties"]["tags"] == {"waterway": "canal", "name": "R-1"}
    dup = {"elements": [payload["elements"][0], payload["elements"][0]]}
    with pytest.raises(IngestionError, match="duplicate"):
        overpass.to_features(dup)
    bad = {"elements": [{**payload["elements"][0], "tags": {"waterway": "river"}}]}
    with pytest.raises(IngestionError, match="unexpected"):
        overpass.to_features(bad)


def test_terrarium_roundtrip_and_tiles():
    h = np.array([[146.69, 160.27], [-5.5, 0.0]])
    back = copdem.terrarium_decode(copdem.terrarium_encode(h))
    assert np.allclose(back, h, atol=1 / 256)
    assert copdem.tile_name(30.78, 72.31) == "Copernicus_DSM_COG_10_N30_00_E072_00_DEM"
    with pytest.raises(IngestionError):
        copdem.terrarium_encode(np.array([[np.nan]]))
