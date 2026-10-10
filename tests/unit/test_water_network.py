"""Network topology/routing (T4.2) and roster caps/curtailment (T4.3). TEST FIXTURE values."""

from datetime import UTC, datetime, timedelta

import pytest

from aabflow.domain.schemas import Edge, Node, RosterWindow, SupplyProfile, SupplyTransformation
from aabflow.water.network import Network, NetworkError
from aabflow.water.roster import SupplyError, resolve_supply, window_cap

H = "0" * 64


def node(nid, kind="junction"):
    return Node(node_id=nid, kind=kind, lon=0, lat=0)


def edge(eid, a, b, f, **kw):
    return Edge(
        edge_id=eid,
        upstream_node_id=a,
        downstream_node_id=b,
        geometry_ref=None,
        delivery_factor=f,
        **kw,
    )


def net(closures=()):
    return Network.from_records(
        [
            node("S", "source"),
            node("M"),
            node("H", "outlet"),
            node("T", "outlet"),
            node("X", "outlet"),
        ],
        [
            edge("e0", "S", "M", 0.95, closures=list(closures)),
            edge("e1", "M", "H", 0.9),
            edge("e2", "H", "T", 0.8),
            edge("e3", "M", "X", 0.85),
        ],
    )


def test_recursive_intake_no_double_factor():
    n = net()
    legs = n.route(100.0, n.path_edges("T"))
    assert [leg.edge_id for leg in legs] == ["e0", "e1", "e2"]
    assert legs[-1].delivered_m3 == pytest.approx(100.0)
    assert legs[-1].intake_m3 == pytest.approx(125.0)
    assert legs[1].intake_m3 == pytest.approx(125.0 / 0.9)
    assert legs[0].intake_m3 == pytest.approx(125.0 / 0.9 / 0.95)
    # each leg's delivery is the next leg's intake: factors applied exactly once
    assert legs[0].delivered_m3 == pytest.approx(legs[1].intake_m3)
    total_loss = sum(leg.loss_m3 for leg in legs)
    assert legs[0].intake_m3 - total_loss == pytest.approx(100.0)


def test_shared_edge_sums_demands():
    n = net()
    a = n.route(50.0, n.path_edges("T"))
    b = n.route(40.0, n.path_edges("X"))
    shared = a[0].intake_m3 + b[0].intake_m3
    assert shared == pytest.approx(50 / 0.8 / 0.9 / 0.95 + 40 / 0.85 / 0.95)


def test_invalid_topologies_rejected():
    with pytest.raises(NetworkError, match="two incoming"):
        Network.from_records(
            [node("S", "source"), node("A"), node("B")],
            [edge("a", "S", "A", 0.9), edge("b", "S", "B", 0.9), edge("c", "B", "A", 0.9)],
        )
    with pytest.raises(NetworkError, match="unknown node"):
        Network.from_records([node("S", "source")], [edge("a", "S", "Z", 0.9)])
    with pytest.raises(NetworkError, match="cycle|no supply"):
        Network.from_records(
            [node("A"), node("B")], [edge("a", "A", "B", 0.9), edge("b", "B", "A", 0.9)]
        )
    with pytest.raises(ValueError):
        edge("bad", "S", "A", 0.0)  # delivery factor must be in (0, 1]


T0 = datetime(2027, 1, 4, 6, tzinfo=UTC)


def window(
    rate=0.04, hours=5, boundary_node="M", basis="time", vol=None, accounting="outlet", node_="T"
):
    return RosterWindow(
        window_id="w1",
        field_id="f",
        outlet_node_id=boundary_node,
        start=T0,
        end=T0 + timedelta(hours=hours),
        basis=basis,
        rate_m3_s=rate if basis == "time" else None,
        volume_cap_m3=vol,
        accounting_boundary=accounting,
        source_rule="TEST FIXTURE",
    )


def supply(*tr, pre=False):
    return SupplyProfile(
        supply_profile_id="s",
        base_profile_hash=H,
        label="t",
        transformations=list(tr),
        resolved_hash=H,
        pre_reduced=pre,
    )


def test_time_right_cap_at_mogha_and_field():
    n = net()
    c = window_cap(window(), "T", n, resolve_supply(supply()))
    assert c.boundary_cap_m3 == pytest.approx(0.04 * 5 * 3600)
    assert c.field_cap_m3 == pytest.approx(0.04 * 5 * 3600 * 0.9 * 0.8)  # tail receives less


def test_curtailment_applied_once_and_transformations():
    n = net()
    absolute = SupplyTransformation(
        transformation_id="a", kind="absolute_multiplier", multiplier=0.78
    )
    rel = SupplyTransformation(transformation_id="r", kind="relative_multiplier", multiplier=0.5)
    rs = resolve_supply(supply(absolute, rel))
    assert rs.multiplier == pytest.approx(0.39)
    full = window_cap(window(), "T", n, resolve_supply(supply())).field_cap_m3
    assert window_cap(window(), "T", n, rs).field_cap_m3 == pytest.approx(full * 0.39)
    with pytest.raises(SupplyError, match="twice"):
        resolve_supply(supply(absolute, absolute))
    with pytest.raises(SupplyError, match="pre-reduced"):
        resolve_supply(supply(absolute, pre=True), extra_uniform_reduction=0.22)
    assert resolve_supply(supply(), extra_uniform_reduction=0.22).multiplier == pytest.approx(0.78)


def test_closures_remove_time_and_close_route():
    half = SupplyTransformation(
        transformation_id="c", kind="closure", start=T0, end=T0 + timedelta(hours=2.5)
    )
    n = net()
    full = window_cap(window(), "T", n, resolve_supply(supply()))
    part = window_cap(window(), "T", n, resolve_supply(supply(half)))
    assert part.field_cap_m3 == pytest.approx(full.field_cap_m3 / 2)
    closed_edge = net(closures=[(T0 - timedelta(hours=1), T0 + timedelta(hours=10))])
    assert window_cap(window(), "T", closed_edge, resolve_supply(supply())).field_cap_m3 == 0.0
    # closure on an edge not on this path does not affect it
    other = SupplyTransformation(
        transformation_id="o",
        kind="closure",
        start=T0,
        end=T0 + timedelta(hours=5),
        edge_ids=["e3"],
    )
    assert window_cap(
        window(), "T", n, resolve_supply(supply(other))
    ).field_cap_m3 == pytest.approx(full.field_cap_m3)


def test_volume_basis_and_field_inlet_boundary():
    n = net()
    v = window_cap(window(basis="volume", vol=500.0), "T", n, resolve_supply(supply()))
    assert v.boundary_cap_m3 == pytest.approx(500.0) and v.field_cap_m3 == pytest.approx(500 * 0.72)
    fi = window_cap(
        window(boundary_node="T", accounting="field_inlet"), "T", n, resolve_supply(supply())
    )
    assert fi.field_cap_m3 == pytest.approx(0.04 * 5 * 3600)
    with pytest.raises(SupplyError):
        window_cap(
            window(boundary_node="M", accounting="field_inlet"), "T", n, resolve_supply(supply())
        )


def test_repair_override_changes_tail_cap():
    n = net()
    base = window_cap(window(), "T", n, resolve_supply(supply())).field_cap_m3
    rep = window_cap(
        window(), "T", n, resolve_supply(supply()), factor_overrides={"e2": 0.95}
    ).field_cap_m3
    assert rep == pytest.approx(base / 0.8 * 0.95)


def test_split_attributes_volume_to_pieces():
    n = net()
    c = window_cap(window(), "T", n, resolve_supply(supply()), boundaries=[T0 + timedelta(hours=1)])
    parts = c.split(100.0)
    assert len(parts) == 2 and sum(v for _, v in parts) == pytest.approx(100.0)
    assert parts[0][1] == pytest.approx(20.0)
