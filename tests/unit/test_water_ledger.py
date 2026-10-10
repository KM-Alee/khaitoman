"""Ledger, rights, pumps, commissioning, costs (T4, T12.1; AT04, AT12 water side).

Uses the labelled synthetic fixture pilot (tests/fixtures/science_fixture_pilot.py)
and synthetic weather. Crop yields here are placeholder TEST values: these tests
exercise physical validation only (crop artifacts are checked in tests/scientific).
"""

import json
from datetime import date, timedelta

import pytest

from aabflow.domain.calendar import local_crop_date, to_utc
from aabflow.domain.schemas import CandidatePolicy, IrrigationEvent, LedgerEvent, LedgerEventKind
from aabflow.optimizer.candidates import (
    build_policy,
    enforce_daily_limit,
    field_view,
    finalize_pond,
    make_templates,
)
from aabflow.water.context import load_pilot
from aabflow.water.ledger import build_season_context, evaluate_events, reconstruct
from tests.fixtures.science_fixture_pilot import FIXTURE_ID, FIXTURE_VERSION, science_env

K = LedgerEventKind
FAKE = "f" * 64  # placeholder crop-outcome hash (physical tests only)
SEASON = "wheat-rabi-2027-28"


@pytest.fixture
def env(tmp_path, monkeypatch):
    return science_env(tmp_path, monkeypatch)


def ctx_for(season=SEASON):
    return build_season_context(load_pilot(FIXTURE_ID), season)


def fake_outcomes(ctx):
    return {w: (FAKE, 5000.0) for w in ctx.weather}


def templates(ctx, fid, cfg="cfg:base"):
    ts = make_templates(ctx, field_view(ctx, fid, cfg), cfg)
    for t in ts:
        enforce_daily_limit(ctx, t)
        finalize_pond(ctx, t)
    return ts


def policy(ctx, fid, family, cfg="cfg:base", pred=lambda t: True):
    t = next(t for t in templates(ctx, fid, cfg) if t.family == family and pred(t))
    return build_policy(ctx, t, fake_outcomes(ctx), ctx.pilot.fields_hash())


def manual(ctx, fid, receipts=(), pumps=(), area=None, cfg="cfg:base", instances=(), uses=(), eff=None):
    """Hand-built policy: receipts [(window_id, m3)] applied on receipt; pumps [(asset, date, m3)]."""
    f = ctx.pilot.fields[fid]
    area = area or f.gross_area_ha
    rec, sched = [], {}
    for wid, v in receipts:
        w = ctx.windows[wid]
        rec.append(LedgerEvent(event_id=f"rcpt:{fid}:{wid}", timestamp=to_utc(w.end), kind=K.outlet_receipt,
                               volume_m3=v, field_id=fid, window_id=wid))
        d = local_crop_date(w.end)
        sched[d] = sched.get(d, 0) + v / (area * 10)
    pev = []
    for aid, d, v in pumps:
        from aabflow.optimizer.candidates import at_local

        pev.append(LedgerEvent(event_id=f"pump:{aid}:{fid}:{d}", timestamp=at_local(d, 7),
                               kind=K.pump_abstraction, volume_m3=v, asset_id=aid, field_id=fid))
        sched[d] = sched.get(d, 0) + v / (area * 10)
    return CandidatePolicy(
        candidate_policy_id=f"cp_manual_{fid}_{len(rec)}_{len(pev)}", candidate_policy_hash="a" * 64,
        field_id=fid, crop_profile_id=ctx.crop.crop_profile_id, soil_profile_id=f.soil_profile_id,
        shared_configuration_id=cfg, required_instance_ids=list(instances), family="manual_test",
        receipt_events=rec, application_schedule=[IrrigationEvent(date=d, gross_depth_mm=v) for d, v in sched.items()],
        pump_events=pev, application_efficiency=eff or f.existing_application_efficiency, cropped_area_ha=area,
        outcomes=[], generator_version="test", uses_asset_ids=list(uses))


def rules(report_or_residuals):
    rs = getattr(report_or_residuals, "residuals", None)
    if isinstance(rs, list):
        return {r.rule for r in rs if not r.passed}
    return {r.rule for r in report_or_residuals.failures}


def nominal(ctx):
    return ctx.resolved["nominal-roster-v1"]


def test_context_states_configs_and_shared_cost_once(env):
    ctx = ctx_for()
    assert len(ctx.state_ids()) == 9 and ctx.typical_state_id() == "typical__nominal-roster-v1"
    cfgs = ctx.configs
    assert set(cfgs) == {"cfg:base", "cfg:fx:fx-e-mid:repair"}
    rep = cfgs["cfg:fx:fx-e-mid:repair"]
    assert rep.capex_pkr == 500000 and rep.edge_delivery_factors == {"fx-e-mid": 0.95}  # charged once per config
    assert cfgs["cfg:base"].capex_pkr == 0


def test_zero_receipt_policy_deliverable_in_every_state(env):
    ctx = ctx_for()
    p = policy(ctx, "fx-f3", "rainfed")
    assert not p.receipt_events and all(o.deliverable for o in p.outcomes) and len(p.outcomes) == 9


def test_b0_exists_per_supply_and_respects_curtailment(env):
    ctx = ctx_for()
    b0 = [t for t in templates(ctx, "fx-f1") if t.family == "baseline_B0"]
    assert {t.params["supply"] for t in b0} == set(ctx.resolved)
    p = policy(ctx, "fx-f1", "baseline_B0", pred=lambda t: t.params["supply"] == "shortage-22pct-v1")
    by = {o.state_id: o for o in p.outcomes}
    assert by["typical__shortage-22pct-v1"].deliverable and by["typical__nominal-roster-v1"].deliverable
    full = policy(ctx, "fx-f1", "baseline_B0", pred=lambda t: t.params["supply"] == "nominal-roster-v1")
    bf = {o.state_id: o for o in full.outcomes}
    assert not bf["typical__shortage-22pct-v1"].deliverable  # nominal habit cannot be forced into a shortage
    assert bf["typical__shortage-22pct-v1"].yield_kg_ha is None


def test_at04_closed_route_receipt_rejected(env):
    ctx = ctx_for()
    closed = next(w for w in ctx.windows_by_field["fx-f1"] if local_crop_date(w.end) == date(2027, 12, 27))
    p = manual(ctx, "fx-f1", [(closed.window_id, 100.0)])
    ev = evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base")
    assert "route_open" in rules(ev.residuals)
    open_w = ctx.windows_by_field["fx-f1"][1]
    ok = manual(ctx, "fx-f1", [(open_w.window_id, 100.0)])
    assert evaluate_events(ok, ctx, nominal(ctx), "typical", "cfg:base").residuals.ok


def test_receipt_above_window_cap_rejected(env):
    ctx = ctx_for()
    w = ctx.windows_by_field["fx-f3"][1]
    cap = ctx.cap(w.window_id, nominal(ctx), "cfg:base").field_cap_m3
    assert cap == pytest.approx(0.04 * 5 * 3600 * 0.9 * 0.85 * 0.8)
    p = manual(ctx, "fx-f3", [(w.window_id, cap * 1.01)])
    assert "receipt_right" in rules(evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals)
    # within cap under nominal, above cap under the 22% shortage
    p2 = manual(ctx, "fx-f3", [(w.window_id, cap * 0.9)])
    assert evaluate_events(p2, ctx, nominal(ctx), "typical", "cfg:base").residuals.ok
    short = ctx.resolved["shortage-22pct-v1"]
    assert "receipt_right" in rules(evaluate_events(p2, ctx, short, "typical", "cfg:base").residuals)


def test_receipt_outside_own_windows_and_wrong_time_rejected(env):
    ctx = ctx_for()
    other = ctx.windows_by_field["fx-f2"][1]
    p = manual(ctx, "fx-f1", [])
    p.receipt_events = [LedgerEvent(event_id="x", timestamp=to_utc(other.end), kind=K.outlet_receipt,
                                    volume_m3=10, field_id="fx-f1", window_id=other.window_id)]
    assert "receipt_right" in rules(evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals)
    own = ctx.windows_by_field["fx-f1"][1]
    p.receipt_events = [LedgerEvent(event_id="y", timestamp=to_utc(own.end) - timedelta(days=1),
                                    kind=K.outlet_receipt, volume_m3=10, field_id="fx-f1", window_id=own.window_id)]
    assert "receipt_right" in rules(evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals)


def test_field_balance_mismatch_rejected(env):
    ctx = ctx_for()
    w = ctx.windows_by_field["fx-f1"][1]
    p = manual(ctx, "fx-f1", [(w.window_id, 100.0)])
    p.application_schedule = [IrrigationEvent(date=p.application_schedule[0].date, gross_depth_mm=9.0)]
    assert "field_balance" in rules(evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals)


def test_at04_shared_pump_excess_rejected_jointly(env):
    ctx = ctx_for()
    d = ctx.planting + timedelta(days=60)
    a = manual(ctx, "fx-f2", pumps=[("fx-pump-1", d, 500.0)], uses=["fx-pump-1"])
    b = manual(ctx, "fx-f3", pumps=[("fx-pump-1", d, 500.0)], uses=["fx-pump-1"])
    for p in (a, b):  # each alone is within the 720 m3/day pump capacity
        assert evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals.ok
    lib = _lib_stub(ctx)
    _, rep = reconstruct([a.candidate_policy_id, b.candidate_policy_id], lib, "typical__nominal-roster-v1",
                         "cfg:base", ctx=ctx, policies={a.candidate_policy_id: a, b.candidate_policy_id: b},
                         check_crop_outcomes=False)
    assert rep.status == "failed" and "pump_rate" in rules(rep)
    # seasonal cap shared across fields: 3 x 2500 m3 > 6000 m3 even on different days
    ps = {}
    for i, fid in enumerate(["fx-f2", "fx-f3", "fx-f4"]):
        days = [ctx.planting + timedelta(days=30 + 10 * i + k) for k in range(5)]
        ps[fid] = manual(ctx, fid, pumps=[("fx-pump-1", dd, 500.0) for dd in days], uses=["fx-pump-1"])
    _, rep2 = reconstruct([p.candidate_policy_id for p in ps.values()], lib, "typical__nominal-roster-v1",
                          "cfg:base", ctx=ctx, policies={p.candidate_policy_id: p for p in ps.values()},
                          check_crop_outcomes=False)
    assert "pump_seasonal_cap" in rules(rep2) and "pump_rate" not in rules(rep2)


def test_pump_access_restricted(env):
    ctx = ctx_for()
    p = manual(ctx, "fx-f1", pumps=[("fx-pump-1", ctx.planting + timedelta(days=50), 100.0)], uses=["fx-pump-1"])
    assert "pump_access" in rules(evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals)


def test_at04_missing_costs_rejected(env, tmp_path):
    d = tmp_path / "pilots" / FIXTURE_ID / FIXTURE_VERSION
    iv = json.loads((d / "interventions.json").read_text())
    for inst in iv["instances"]:
        if inst["instance_id"] == "fx:fx-f1:leveling":
            inst["capex_pkr"] = 0
    (d / "interventions.json").write_text(json.dumps(iv))
    assets = json.loads((d / "assets.json").read_text())
    for a in assets:
        if a["asset_id"] == "fx-pump-1":
            a["cost_per_m3_pkr"] = None
    (d / "assets.json").write_text(json.dumps(assets))
    ctx = ctx_for()
    assert "capex missing" in ctx.excluded_instances["fx:fx-f1:leveling"]
    assert "fx:fx-pump-1:supplement" in ctx.excluded_instances
    lev = manual(ctx, "fx-f1", instances=["fx:fx-f1:leveling"], eff=0.75)
    assert "cost_completeness" in rules(evaluate_events(lev, ctx, nominal(ctx), "typical", "cfg:base").residuals)
    pump = manual(ctx, "fx-f2", pumps=[("fx-pump-1", ctx.planting + timedelta(days=50), 100.0)], uses=["fx-pump-1"])
    assert "pump_cost" in rules(evaluate_events(pump, ctx, nominal(ctx), "typical", "cfg:base").residuals)
    # candidates never generate pump or leveling options without costs
    fams = {t.family for t in templates(ctx, "fx-f2")} | {t.family for t in templates(ctx, "fx-f1")}
    assert not any(f.startswith("pump") or "leveling" in f for f in fams)


def test_at04_premature_commissioning_rejected(env):
    ctx = ctx_for("wheat-rabi-2026-27")  # decision 10 Oct 2026, planting 15 Nov 2026
    assert "after planting" in ctx.excluded_instances["fx:fx-f4:pond-small"]
    assert "after planting" in ctx.excluded_instances["fx:fx-e-mid:repair"]
    assert set(ctx.configs) == {"cfg:base"}
    assert "fx:fx-f1:leveling" not in ctx.excluded_instances  # 25-day leveling fits
    p = manual(ctx, "fx-f4", instances=["fx:fx-f4:pond-small"], area=1.0 - 420 / 10000)
    assert "commissioning" in rules(evaluate_events(p, ctx, nominal(ctx), "typical", "cfg:base").residuals)
    fams = {t.family for t in templates(ctx, "fx-f4")}
    assert not any(f.startswith("pond") for f in fams)


def test_at12_pond_land_removed_once(env):
    ctx = ctx_for("cotton-kharif-2027")
    p = policy(ctx, "fx-f4", "pond_shift")
    assert "fx:fx-f4:pond-small" in p.required_instance_ids
    assert p.cropped_area_ha == pytest.approx(1.0 - 420 / 10000)
    assert any(o.deliverable for o in p.outcomes)
    bad = p.model_copy(update={"cropped_area_ha": 1.0})
    assert "area" in rules(evaluate_events(bad, ctx, nominal(ctx), "typical", "cfg:base").residuals)
    # existing pond footprint is already outside the baseline area: not subtracted again
    ex = policy(ctx, "fx-f3", "pond_shift")
    assert ex.cropped_area_ha == pytest.approx(2.0) and "fx-pond-f3" in ex.uses_asset_ids


def test_pumping_charged_to_operating_budget(env):
    ctx = ctx_for()
    p = policy(ctx, "fx-f2", "pump_topup")
    assert p.pump_volume_m3 > 0
    assert p.seasonal_opex_pkr == pytest.approx(int(-(-p.pump_volume_m3 * 4.5 // 1)), abs=1)


def _lib_stub(ctx):
    from datetime import UTC, datetime

    from aabflow.domain.schemas import CandidateLibrary

    return CandidateLibrary(candidate_library_hash="b" * 64, pilot_id=FIXTURE_ID, pilot_version=FIXTURE_VERSION,
                            season_id=ctx.season.season_id, state_ids=ctx.state_ids(),
                            configurations=list(ctx.configs.values()), policies_ref="x", coverage=[],
                            generator_version="test", created_at=datetime.now(UTC))


def test_reconstruct_valid_plan_balances(env):
    ctx = ctx_for()
    pols = {}
    for fid in ["fx-f1", "fx-f2", "fx-f3", "fx-f4"]:
        p = policy(ctx, fid, "full_window", pred=lambda t: "supply:nominal-roster-v1" in t.tags)
        pols[p.candidate_policy_id] = p
    events, rep = reconstruct(list(pols), _lib_stub(ctx), "typical__nominal-roster-v1", "cfg:base", ctx=ctx,
                              policies=pols, check_crop_outcomes=False)
    assert rep.status == "passed", [r for r in rep.residuals if not r.passed]
    keys = [(to_utc(e.timestamp), e.explicit_order, e.event_id) for e in events]
    assert keys == sorted(keys)
    transfers = {e.event_id[5:]: e.volume_m3 for e in events if e.kind is K.edge_transfer}
    losses = {e.event_id[5:]: e.volume_m3 for e in events if e.kind is K.edge_loss}
    eta = {e.edge_id: e.delivery_factor for e in ctx.pilot.edges}
    for k, v in transfers.items():
        assert losses[k] == pytest.approx(v * (1 - eta[k.split(":")[0]]))
    receipts = sum(e.volume_m3 for e in events if e.kind is K.outlet_receipt)
    source = sum(e.volume_m3 for e in events if e.kind is K.source_release)
    assert source - sum(losses.values()) == pytest.approx(receipts)
    # two policies for one field are rejected
    extra = policy(ctx, "fx-f1", "rainfed")
    pols2 = {**pols, extra.candidate_policy_id: extra}
    _, rep2 = reconstruct(list(pols2), _lib_stub(ctx), "typical__nominal-roster-v1", "cfg:base", ctx=ctx,
                          policies=pols2, check_crop_outcomes=False)
    assert rep2.status == "failed"


def test_edge_capacity_checked_jointly(env, tmp_path):
    d = tmp_path / "pilots" / FIXTURE_ID / FIXTURE_VERSION
    net = json.loads((d / "network.json").read_text())
    net["edges"][0]["capacities"][0]["max_rate_m3_s"] = 0.03  # below the 0.04/0.95 full-turn intake
    (d / "network.json").write_text(json.dumps(net))
    ctx = ctx_for()
    p = policy(ctx, "fx-f1", "full_window", pred=lambda t: "supply:nominal-roster-v1" in t.tags)
    _, rep = reconstruct([p.candidate_policy_id], _lib_stub(ctx), "typical__nominal-roster-v1", "cfg:base",
                         ctx=ctx, policies={p.candidate_policy_id: p}, check_crop_outcomes=False)
    assert "edge_capacity" in rules(rep)


def test_interruption_state_blocks_closed_windows(env):
    ctx = ctx_for()
    p = policy(ctx, "fx-f1", "full_window", pred=lambda t: "supply:nominal-roster-v1" in t.tags)
    by = {o.state_id: o for o in p.outcomes}
    assert not by["typical__interruption-14d-v1"].deliverable
    assert any("route_open" in v for v in by["typical__interruption-14d-v1"].violations)
    r = policy(ctx, "fx-f1", "robust")
    assert all(o.deliverable for o in r.outcomes)
