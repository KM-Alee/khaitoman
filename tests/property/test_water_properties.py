"""Hypothesis properties for routing, pond chronology and roster caps (T12.1).

Oracles are written independently of the implementation (walk-up path factors,
a plain running-sum simulator) and every generated valid case is perturbed in a
single constraint to produce an expected failure, including event-order mutations.
"""

from datetime import UTC, datetime, timedelta

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from aabflow.domain.schemas import (
    Edge,
    LedgerEvent,
    LedgerEventKind,
    Node,
    RosterWindow,
    SupplyProfile,
)
from aabflow.water.network import Network
from aabflow.water.pond import chronology
from aabflow.water.roster import resolve_supply, window_cap

K = LedgerEventKind
T0 = datetime(2027, 1, 1, tzinfo=UTC)
SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def trees(draw):
    n = draw(st.integers(min_value=2, max_value=9))
    parents = [draw(st.integers(min_value=0, max_value=i - 1)) for i in range(1, n)]
    factors = [draw(st.floats(min_value=0.5, max_value=1.0)) for _ in range(1, n)]
    nodes = [Node(node_id="n0", kind="source", lon=0, lat=0)] + [
        Node(node_id=f"n{i}", kind="outlet", lon=0, lat=0) for i in range(1, n)
    ]
    edges = [
        Edge(
            edge_id=f"e{i}",
            upstream_node_id=f"n{p}",
            downstream_node_id=f"n{i}",
            geometry_ref=None,
            delivery_factor=f,
        )
        for i, (p, f) in enumerate(zip(parents, factors, strict=True), start=1)
    ]
    return nodes, edges, parents, factors


@SETTINGS
@given(trees(), st.data())
def test_routing_conserves_mass_against_walkup_oracle(tree, data):
    nodes, edges, parents, factors = tree
    net = Network.from_records(nodes, edges)
    n = len(nodes)
    deliveries = {f"n{i}": data.draw(st.floats(min_value=0, max_value=1000)) for i in range(1, n)}
    intake: dict[str, float] = {}
    total_loss = 0.0
    for nid, d in deliveries.items():
        legs = net.route(d, net.path_edges(nid))
        for leg in legs:
            intake[leg.edge_id] = intake.get(leg.edge_id, 0.0) + leg.intake_m3
            assert leg.loss_m3 >= -1e-9
            total_loss += leg.loss_m3
        # oracle: walk up parents multiplying factors
        prod, i = 1.0, int(nid[1:])
        while i != 0:
            prod *= factors[i - 1]
            i = parents[i - 1]
        root_edge = legs[0].intake_m3 if legs else 0.0
        assert abs(root_edge - d / prod) <= 1e-6 * max(1.0, d / prod)
    source = sum(v for eid, v in intake.items() if net.edges[eid].upstream_node_id == "n0")
    assert abs(source - total_loss - sum(deliveries.values())) <= 1e-6 * max(1.0, source)


def oracle_ok(events, cap, init):
    s = init
    for e in sorted(events, key=lambda e: (e.timestamp, e.explicit_order, e.event_id)):
        s += e.volume_m3 if e.kind in (K.pond_fill, K.pond_rain) else -e.volume_m3
        if s < -1e-6 or s > cap + 1e-6:
            return False
    return True


@st.composite
def valid_traces(draw):
    cap = draw(st.floats(min_value=50, max_value=2000))
    init = draw(st.floats(min_value=0, max_value=1)) * cap
    s, events = init, []
    for i in range(draw(st.integers(min_value=1, max_value=25))):
        ts = T0 + timedelta(hours=6 * i)
        if draw(st.booleans()):
            v = max(0.0, draw(st.floats(min_value=0, max_value=1)) * (cap - s))
            kind = K.pond_fill
            s += v
        else:
            v = max(0.0, draw(st.floats(min_value=0, max_value=1)) * s)
            kind = draw(st.sampled_from([K.pond_release, K.pond_evaporation, K.pond_seepage]))
            s -= v
        events.append(
            LedgerEvent(event_id=f"e{i:03d}", timestamp=ts, kind=kind, volume_m3=v, asset_id="p")
        )
    return cap, init, events


@SETTINGS
@given(valid_traces())
def test_valid_traces_pass_and_balance(trace):
    cap, init, events = trace
    tr = chronology(events, cap, init, "p")
    assert tr.residuals.ok, tr.residuals.reasons()
    inflow = sum(e.volume_m3 for e in events if e.kind is K.pond_fill)
    outflow = sum(e.volume_m3 for e in events if e.kind is not K.pond_fill)
    assert abs(init + inflow - outflow - tr.terminal_m3) <= 1e-6 * max(1.0, cap)


@SETTINGS
@given(valid_traces(), st.data())
def test_single_perturbation_is_rejected(trace, data):
    cap, init, events = trace
    releases = [i for i, e in enumerate(events) if e.kind is K.pond_release]
    fills = [i for i, e in enumerate(events) if e.kind is K.pond_fill and e.volume_m3 > 1.0]
    choice = data.draw(st.sampled_from(["over_release", "shrink_capacity"]))
    if choice == "over_release":
        assume(releases)
        i = data.draw(st.sampled_from(releases))
        mutated = list(events)
        mutated[i] = events[i].model_copy(update={"volume_m3": events[i].volume_m3 + cap * 3})
        assert not chronology(mutated, cap, init, "p").residuals.ok
    else:
        assume(fills)
        tr = chronology(events, cap, init, "p")
        peak = max([init, *tr.inventory_after])
        assume(peak > 1.0 and init <= peak * 0.9)
        assert not chronology(events, peak * 0.9, init, "p").residuals.ok


@SETTINGS
@given(valid_traces(), st.data())
def test_event_order_mutation_matches_independent_oracle(trace, data):
    cap, init, events = trace
    assume(len(events) >= 2)
    i = data.draw(st.integers(min_value=0, max_value=len(events) - 1))
    j = data.draw(st.integers(min_value=0, max_value=len(events) - 1))
    assume(i != j)
    mutated = list(events)
    ti, tj = events[i].timestamp, events[j].timestamp
    mutated[i] = events[i].model_copy(update={"timestamp": tj, "explicit_order": 1})
    mutated[j] = events[j].model_copy(update={"timestamp": ti, "explicit_order": 0})
    assert chronology(mutated, cap, init, "p").residuals.ok == oracle_ok(mutated, cap, init)


@SETTINGS
@given(
    st.floats(min_value=0.001, max_value=0.2),
    st.floats(min_value=0.25, max_value=12),
    st.floats(min_value=0, max_value=1),
    st.floats(min_value=0, max_value=1),
    st.floats(min_value=0, max_value=1),
)
def test_window_cap_monotone_and_bounded(rate, hours, m1, c0, c1):
    nodes = [
        Node(node_id="s", kind="source", lon=0, lat=0),
        Node(node_id="m", kind="junction", lon=0, lat=0),
        Node(node_id="f", kind="outlet", lon=0, lat=0),
    ]
    edges = [
        Edge(
            edge_id="a",
            upstream_node_id="s",
            downstream_node_id="m",
            geometry_ref=None,
            delivery_factor=0.95,
        ),
        Edge(
            edge_id="b",
            upstream_node_id="m",
            downstream_node_id="f",
            geometry_ref=None,
            delivery_factor=0.8,
        ),
    ]
    net = Network.from_records(nodes, edges)
    w = RosterWindow(
        window_id="w",
        field_id="x",
        outlet_node_id="m",
        start=T0,
        end=T0 + timedelta(hours=hours),
        rate_m3_s=rate,
        source_rule="TEST FIXTURE",
    )
    h = "0" * 64
    lo, hi = sorted((c0, c1))
    tr_close = {
        "transformation_id": "c",
        "kind": "closure",
        "start": T0 + timedelta(hours=hours * lo),
        "end": T0 + timedelta(hours=hours * hi + 1e-3),
    }
    base = window_cap(
        w,
        "f",
        net,
        resolve_supply(
            SupplyProfile(supply_profile_id="n", base_profile_hash=h, label="n", resolved_hash=h)
        ),
    )
    cur = window_cap(
        w,
        "f",
        net,
        resolve_supply(
            SupplyProfile(
                supply_profile_id="c",
                base_profile_hash=h,
                label="c",
                resolved_hash=h,
                transformations=[
                    {"transformation_id": "m", "kind": "absolute_multiplier", "multiplier": m1},
                    tr_close,
                ],
            )
        ),
    )
    full = rate * hours * 3600
    assert abs(base.boundary_cap_m3 - full) <= 1e-6 * full
    assert abs(base.field_cap_m3 - full * 0.8) <= 1e-6 * full
    assert cur.field_cap_m3 <= base.field_cap_m3 * m1 + 1e-9
    wend = T0 + timedelta(hours=hours)
    closed = max(0.0, (min(tr_close["end"], wend) - max(tr_close["start"], T0)).total_seconds())
    expected = rate * m1 * 0.8 * (hours * 3600 - closed)
    assert abs(cur.field_cap_m3 - expected) <= 1e-6 * full + 1e-9
