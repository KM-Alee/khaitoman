"""Field review rules, declared network, roster/assets/interventions builders (synthetic fixtures)."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Polygon, box, mapping

from aabflow.domain.schemas import ActionCategory, AssetKind
from aabflow.ingestion.aoi import Aoi, to_metric, to_wgs84
from aabflow.ingestion.packages import network as netmod
from aabflow.ingestion.packages import operations as ops
from aabflow.ingestion.packages.validate import check_graph, check_roster
from aabflow.ingestion.review.fields import ManualEdit, ReviewConfig, review

AOI = Aoi.from_bbox(72.306, 30.776, 72.330, 30.798)
CRS = AOI.metric_crs
X0, Y0 = to_metric(AOI.geometry, CRS).bounds[:2]


def mfeat(fid, geom_m):
    return {"type": "Feature", "id": fid, "geometry": mapping(to_wgs84(geom_m, CRS)),
            "properties": {"model_id": fid}}  # fmt: skip


def grid_fields(n=36, w=100, h=120, gap=10, x=200, y=200):
    """Synthetic clean rectangular parcels (test fixture, not real fields)."""
    out = []
    cols = 6
    for i in range(n):
        cx, cy = X0 + x + (i % cols) * (w + gap), Y0 + y + (i // cols) * (h + gap)
        out.append(mfeat(f"m{i:03d}", box(cx, cy, cx + w, cy + h)))
    return out


def test_review_selects_30_and_logs_every_raw_polygon():
    feats = grid_fields()
    sliver = mfeat("sliver", box(X0 + 1500, Y0 + 200, X0 + 1520, Y0 + 900))
    tiny = mfeat("tiny", box(X0 + 1600, Y0 + 200, X0 + 1640, Y0 + 240))
    outside = mfeat("outside", box(X0 - 300, Y0 + 300, X0 - 100, Y0 + 400))
    bow = mfeat("bow", Polygon([(X0 + 1800, Y0 + 200), (X0 + 1900, Y0 + 300),
                                (X0 + 1900, Y0 + 200), (X0 + 1800, Y0 + 300)]))  # fmt: skip
    fc = {"type": "FeatureCollection", "features": [*feats, sliver, tiny, outside, bow]}
    r = review(fc, AOI, ReviewConfig(min_area_m2=5000))
    assert len(r.selected) == 30
    by = {e["model_id"]: e for e in r.log}
    assert len(by) == len(fc["features"])
    assert by["sliver"]["decision"] == "rejected"
    assert by["tiny"]["decision"] == "rejected" and "area" in by["tiny"]["reasons"][-1]
    assert by["outside"]["decision"] == "rejected"
    assert "repaired_invalid" in by["bow"]["actions"]
    assert r.summary["selected"] == 30 and r.summary["raw_polygons"] == len(fc["features"])
    assert sum(1 for e in r.log if e["decision"] == "eligible_not_selected") == 6


def test_overlap_is_clipped_from_lower_quality_polygon():
    feats = grid_fields(30)
    a = box(X0 + 1500, Y0 + 1500, X0 + 1600, Y0 + 1620)
    b = Polygon(
        [
            (X0 + 1590, Y0 + 1500),
            (X0 + 1700, Y0 + 1500),
            (X0 + 1700, Y0 + 1620),
            (X0 + 1590, Y0 + 1610),
        ]
    )
    fc = {"type": "FeatureCollection", "features": [*feats, mfeat("a", a), mfeat("b", b)]}
    r = review(fc, AOI, ReviewConfig(min_area_m2=5000))
    clipped = [c for c in r.all if "overlap_clipped" in c.actions]
    assert len(clipped) == 1
    sel = {c.model_id: c.geom_m for c in r.all if not c.rejected}
    assert sel["a"].intersection(sel["b"]).area < 1e-6


def test_too_few_eligible_raises():
    with pytest.raises(ValueError, match="eligible"):
        review(
            {"type": "FeatureCollection", "features": grid_fields(10)},
            AOI,
            ReviewConfig(min_area_m2=5000),
        )


def test_duplicate_model_ids_rejected():
    f = grid_fields(2)
    f[1]["id"] = f[0]["id"]
    with pytest.raises(ValueError, match="duplicate"):
        review({"type": "FeatureCollection", "features": f}, AOI)


def test_manual_edits_and_canal_exclusion():
    feats = grid_fields(40)
    canal = to_wgs84(LineString([(X0 + 195, Y0), (X0 + 195 + 1, Y0 + 2000)]).buffer(10), CRS)
    edits = [ManualEdit("m001", "reject", "visibly merged with neighbour")]
    r = review({"type": "FeatureCollection", "features": feats}, AOI, ReviewConfig(min_area_m2=5000),
               manual_edits=edits, exclusion_wgs84=[canal])  # fmt: skip
    by = {e["model_id"]: e for e in r.log}
    assert by["m001"]["decision"] == "rejected"
    assert any("canal" in x for x in by["m000"]["reasons"])  # first column touches the canal buffer
    with pytest.raises(ValueError, match="unknown model id"):
        review(
            {"type": "FeatureCollection", "features": feats},
            AOI,
            manual_edits=[ManualEdit("zz", "reject", "x")],
        )


def _network():
    sites = []
    for i in range(30):
        cx, cy = X0 + 300 + (i % 6) * 110, Y0 + 300 + (i // 6) * 130
        lon, lat = to_wgs84(box(cx, cy, cx + 100, cy + 120), CRS).centroid.coords[0]
        sites.append(netmod.FieldSite(f"pilot-t:field-{i:03d}", (lon, lat), 12000.0))
    canal_m = LineString([(X0 + 100, Y0), (X0 + 100, Y0 + 2400)])
    parent = {"type": "Feature", "id": "osm:way/1", "geometry": mapping(to_wgs84(canal_m, CRS)),
              "properties": {"source_feature_id": "osm:way/1"}}  # fmt: skip
    clo = [c for c in (ops.closure_interval(s) for s in ops.SEASONS) if c]
    return netmod.build_network("pilot-t", sites, parent, CRS, clo), sites


def test_network_is_tree_with_distinct_reaches():
    net, sites = _network()
    errors: list[str] = []
    parent = check_graph(net.nodes, net.edges, errors)
    assert errors == []
    assert set(net.field_outlet) == {s.field_id for s in sites}
    for reaches in net.reach_edges.values():
        f = [e.delivery_factor for e in net.edges if e.edge_id in reaches]
        assert len(f) == 3 and len(set(f)) == 3
        for e in net.edges:
            if e.edge_id in reaches:
                assert e.geometry_ref is None and e.source_feature_ids == []
    observed = [e for e in net.edges if e.geometry_ref]
    assert all(e.geometry_ref == "osm:way/1" for e in observed)
    tail = next(
        f for f, g in net.field_group.items() if g == "tail" and net.field_watercourse[f] == "wc1"
    )
    pf = netmod.path_factor(net.edges, net.mogha_of["wc1"], net.field_outlet[tail])
    assert pf == pytest.approx(0.93 * 0.86 * 0.79)
    assert parent


def test_graph_check_rejections():
    net, _ = _network()
    e0 = net.edges[-1]
    bad = [*net.edges, e0.model_copy(update={"edge_id": "pilot-t:edge-x"})]
    errs: list[str] = []
    check_graph(net.nodes, bad, errs)
    assert any("more than one upstream" in e for e in errs)
    errs = []
    check_graph(net.nodes, [*net.edges[1:]], errs)
    assert any("exactly one source root" in e for e in errs)
    errs = []
    dang = e0.model_copy(update={"edge_id": "pilot-t:edge-y", "downstream_node_id": "nope"})
    check_graph(net.nodes, [*net.edges, dang], errs)
    assert any("dangling" in e for e in errs)
    errs = []
    cyc = e0.model_copy(update={"edge_id": "pilot-t:edge-z", "upstream_node_id": e0.downstream_node_id,
                                "downstream_node_id": net.edges[0].upstream_node_id})  # fmt: skip
    check_graph(net.nodes, [*net.edges, cyc], errs)
    assert any("cycle" in e or "root" in e for e in errs)


def test_roster_exclusive_area_proportional_and_overlap_rejected():
    net, sites = _network()
    area = {s.field_id: 1.2 for s in sites}
    roster = ops.build_roster("pilot-t", net, area)
    assert set(roster) == {s.season_id for s in ops.SEASONS}
    errs: list[str] = []
    check_roster(roster, errs)
    assert errs == []
    wins = roster["wheat-rabi-2026-27"]
    assert {w.outlet_node_id for w in wins} == set(net.mogha_of.values())
    first = [w for w in wins if w.outlet_node_id == net.mogha_of["wc1"]][:15]
    turn = 7 * 86400 * 1.2 / ops.ASSUMPTIONS["asm:watercourse-cca"].value
    assert (first[0].end - first[0].start).total_seconds() == pytest.approx(turn, abs=1)
    assert (first[-1].start - first[0].start).total_seconds() < 7 * 86400
    rate = ops.watercourse_rate_m3_s(ops.ASSUMPTIONS["asm:watercourse-cca"].value)
    assert first[0].rate_m3_s == pytest.approx(rate, abs=1e-6)
    w0, w1 = first[0], first[1]
    bad = {"s": [w0, w1.model_copy(update={"start": w0.start})]}
    errs = []
    check_roster(bad, errs)
    assert any("overlap" in e for e in errs)


def test_service_reference_tail_below_head():
    net, sites = _network()
    area = {s.field_id: 1.2 for s in sites}
    roster = ops.build_roster("pilot-t", net, area)
    refs = ops.build_service_reference(roster, net, net.edges)
    r = {(x.field_id, x.season_id): x.reference_receipt_m3 for x in refs}
    wc1 = net.watercourse_fields["wc1"]
    head = next(f for f in wc1 if net.field_group[f] == "head")
    tail = next(f for f in wc1 if net.field_group[f] == "tail")
    sid = "wheat-rabi-2026-27"
    assert r[(tail, sid)] < r[(head, sid)]
    # closure removes water: rabi reference < kharif reference of similar length
    assert all(v > 0 for v in r.values())


def test_assets_and_interventions():
    net, sites = _network()
    area = {s.field_id: 12000.0 + i * 100 for i, s in enumerate(sites)}
    ab = ops.build_assets("pilot-t", net, area)
    kinds = {(a.kind, a.existing) for a in ab.assets}
    assert (AssetKind.pond, True) in kinds and (AssetKind.pump, True) in kinds
    pump = next(a for a in ab.assets if a.kind == AssetKind.pump)
    assert len(pump.field_ids) >= 2 and pump.cost_per_m3_pkr == "8.50"
    pond = next(a for a in ab.assets if a.kind == AssetKind.pond)
    assert pond.usable_capacity_m3 == pytest.approx(0.075 * area[ab.pond_field])
    nodes = {n.node_id: n for n in net.nodes}
    lengths = {e.edge_id: netmod.reach_length_m(e, nodes, CRS) for e in net.edges}
    _types, inst = ops.build_interventions("pilot-t", net, net.edges, area, ab, lengths)
    assert {i.category for i in inst} == set(ActionCategory)
    repairs = [i for i in inst if i.category == ActionCategory.shared_repair]
    assert len(repairs) == 2 and all(i.shared and i.capex_pkr > 0 for i in repairs)
    ponds = [i for i in inst if i.category == ActionCategory.pond]
    groups = {}
    for p in ponds:
        groups.setdefault(p.mutually_exclusive_group, []).append(p.parameters["irrigations_held"])
        fid = p.target_ids[0]
        assert p.parameters["usable_capacity_m3"] == pytest.approx(
            p.parameters["irrigations_held"] * 0.075 * area[fid], rel=1e-6
        )
        assert p.lead_time_days == 90 and p.capex_pkr > 0
    assert all(sorted(v) == [0.5, 1.0, 1.5] for v in groups.values())
    assert ab.pond_field not in {i.target_ids[0] for i in ponds}
    lev = [i for i in inst if i.category == ActionCategory.leveling]
    assert len(lev) == 30 and all(i.parameters["application_efficiency_after"] == 0.75 for i in lev)


def test_pond_geometry_scale():
    g = ops.pond_geometry(10_000.0, 1.0)  # one 75 mm irrigation on 1 ha = 750 m³ (T4.4)
    assert g["usable_capacity_m3"] == 750.0
    assert g["surface_area_m2"] == 375.0 and g["footprint_m2"] > g["surface_area_m2"]
