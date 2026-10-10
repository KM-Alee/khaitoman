"""Pond chronology (T4.4) incl. AT03 fixtures. All numbers are TEST FIXTURE values."""

from datetime import UTC, date, datetime, timedelta

import pytest

from aabflow.domain.schemas import LedgerEvent, LedgerEventKind
from aabflow.water.pond import PondSpec, chronology, exogenous_events, size_for_irrigations

K = LedgerEventKind
A = "pond-x"


def ev(eid, ts, kind, v, order=0):
    return LedgerEvent(
        event_id=eid, timestamp=ts, explicit_order=order, kind=kind, volume_m3=v, asset_id=A
    )


T0 = datetime(2027, 1, 1, 6, tzinfo=UTC)


def test_two_period_trace_fixture():
    """T4.4: start 0, fill 120, irrigate 100, loss 5, end 15; next: release 10, loss 1, end 4."""
    p1 = [
        ev("f", T0, K.pond_fill, 120),
        ev("r", T0 + timedelta(hours=2), K.pond_release, 100),
        ev("e", T0 + timedelta(hours=20), K.pond_evaporation, 5),
    ]
    tr1 = chronology(p1, capacity_m3=200, initial_m3=0, asset_id=A)
    assert tr1.residuals.ok and tr1.terminal_m3 == pytest.approx(15)
    assert tr1.inventory_after == pytest.approx([120, 20, 15])
    t1 = T0 + timedelta(days=1)
    p2 = [ev("r2", t1, K.pond_release, 10), ev("s2", t1 + timedelta(hours=20), K.pond_seepage, 1)]
    tr2 = chronology(p2, capacity_m3=200, initial_m3=tr1.terminal_m3, asset_id=A)
    assert tr2.residuals.ok and tr2.terminal_m3 == pytest.approx(4)
    # Nothing disappears between periods: totals reconcile with inventories.
    t = tr1.totals
    assert 0 + t["pond_fill"] - t["pond_release"] - t["pond_evaporation"] == pytest.approx(15)


def test_at03_monday_before_friday_rejected():
    """Using Friday's receipt on the preceding Monday drives inventory negative."""
    monday = datetime(2027, 1, 4, 6, tzinfo=UTC)
    friday = datetime(2027, 1, 8, 6, tzinfo=UTC)
    events = [ev("fill-fri", friday, K.pond_fill, 500), ev("use-mon", monday, K.pond_release, 400)]
    tr = chronology(events, capacity_m3=1000, initial_m3=0, asset_id=A)
    assert not tr.residuals.ok
    rules = {r.rule for r in tr.residuals.failures}
    assert rules == {"pond_nonnegative"}
    bad = tr.residuals.failures[0]
    assert "use-mon" in bad.entity_ids and bad.max_violation == pytest.approx(400)
    # Same volumes in the right order pass: the ledger, not the period total, decides.
    ok = [
        ev("fill-fri", friday, K.pond_fill, 500),
        ev("use-mon", friday + timedelta(days=3), K.pond_release, 400),
    ]
    assert chronology(ok, capacity_m3=1000, initial_m3=0, asset_id=A).residuals.ok


def test_at03_intra_period_over_capacity_rejected():
    """Period end is within capacity, but an intermediate event overflows."""
    events = [
        ev("f1", T0, K.pond_fill, 80),
        ev("f2", T0 + timedelta(hours=1), K.pond_fill, 50),
        ev("r", T0 + timedelta(hours=5), K.pond_release, 60),
    ]
    tr = chronology(events, capacity_m3=100, initial_m3=0, asset_id=A)
    assert tr.terminal_m3 == pytest.approx(70)  # period total looks fine
    fails = tr.residuals.failures
    assert [f.rule for f in fails] == ["pond_capacity"]
    assert fails[0].max_violation == pytest.approx(30) and "f2" in fails[0].entity_ids


def test_simultaneous_events_use_explicit_order():
    same = T0
    fill_first = [
        ev("b", same, K.pond_release, 50, order=1),
        ev("a", same, K.pond_fill, 50, order=0),
    ]
    assert chronology(fill_first, 100, 0, A).residuals.ok
    release_first = [
        ev("a", same, K.pond_release, 50, order=0),
        ev("b", same, K.pond_fill, 50, order=1),
    ]
    assert not chronology(release_first, 100, 0, A).residuals.ok


def test_losses_bounded_by_inventory():
    events = [
        ev("f", T0, K.pond_fill, 10),
        ev("e", T0 + timedelta(hours=1), K.pond_evaporation, 50),
    ]
    tr = chronology(events, 100, 0, A)
    assert "pond_loss_bound" in {f.rule for f in tr.residuals.failures}


def test_exogenous_losses_capped_and_spill_explicit():
    spec = PondSpec(
        asset_id=A,
        usable_capacity_m3=100,
        surface_area_m2=1000,
        initial_inventory_m3=95,
        seepage_m3_day=3,
    )
    days = [date(2027, 1, 1) + timedelta(days=i) for i in range(30)]
    wet = {d: (20.0, 1.0) for d in days[:2]} | {d: (0.0, 6.0) for d in days[2:]}
    exo, tr = exogenous_events(spec, [], wet, days)
    assert tr.residuals.ok, tr.residuals.reasons()
    spills = [e for e in exo if e.kind is K.pond_spill]
    # day 1: 95 + 20 mm x 1000 m2 = 115 -> explicit 15 m3 spill (never silently discarded)
    assert spills and spills[0].volume_m3 == pytest.approx(15)
    assert tr.terminal_m3 >= 0
    assert all(v >= -1e-9 for v in tr.inventory_after)
    total_in = 95 + tr.totals["pond_rain"]
    total_out = sum(tr.totals[k] for k in ("pond_evaporation", "pond_seepage", "pond_spill"))
    assert total_in - total_out == pytest.approx(tr.terminal_m3)


def test_pond_size_in_irrigations():
    vol, surf, foot = size_for_irrigations(1.0, 1.0)
    assert vol == pytest.approx(750.0)  # one 75 mm irrigation on 1 ha
    assert surf == pytest.approx(500.0) and foot > surf


def test_inconsistent_geometry_rejected():
    with pytest.raises(ValueError):
        PondSpec(asset_id=A, usable_capacity_m3=100, surface_area_m2=500, footprint_m2=100)
    with pytest.raises(ValueError):
        PondSpec(asset_id=A, usable_capacity_m3=100, surface_area_m2=50, initial_inventory_m3=150)
