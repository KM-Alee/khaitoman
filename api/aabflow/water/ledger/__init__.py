"""Chronological physical ledger, per-policy evaluation and plan reconstruction (T4, T6.6).

Policy representation (CandidatePolicy, controlled decisions identical in every state):

* ``receipt_events``: ``outlet_receipt`` at the field node, one per taken roster
  window, timestamped at the window end (water counts as available only once
  the turn has completed), volume = water arriving at the field;
* ``pond_events``: controlled ``pond_fill`` (from a receipt, same timestamp,
  later explicit order) and ``pond_release`` (to the field);
* ``pump_events``: ``pump_abstraction`` applied directly to the field;
* ``application_schedule``: daily gross field depth (mm) = (receipt - fill +
  release + pump) / (cropped_area_ha x 10) on that local day.

``evaluate_policy`` validates a policy under one state (weather + resolved
supply + shared configuration) and returns its ``StateOutcome``; ``reconstruct``
re-derives the full event ledger of a selected plan (routing, losses, pond
exogenous terms, pumping, application) and checks shared constraints jointly:
edge/source capacity per atomic interval, node balance, pump sharing, pond
sharing, one policy per field, exact crop outcomes. Events are ordered by
``(timestamp, explicit_order, event_id)``; JSON order is never relied upon.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

from aabflow.domain import units
from aabflow.domain.calendar import PKT, local_crop_date, to_utc
from aabflow.domain.schemas import (
    ActionCategory,
    AssetKind,
    AtomicInterval,
    CandidateLibrary,
    CandidatePolicy,
    CropProfile,
    LedgerEvent,
    LedgerEventKind,
    PhysicalValidationReport,
    ResourceCapacity,
    ResourceUse,
    RosterWindow,
    Season,
    SharedConfiguration,
    StateOutcome,
    SupplyProfile,
    WeatherScenario,
)
from aabflow.science import crop_profiles, scenarios
from aabflow.water.context import (
    PilotData,
    asset_available_on,
    atomic_intervals,
    commissioned_on,
    configurations,
    day_interval_id,
    instance_admissibility,
    load_pilot,
    local_midnight_utc,
    missing_cost,
)
from aabflow.water.network import overlap_seconds
from aabflow.water.pond import PondSpec, chronology, exogenous_events, sort_key
from aabflow.water.pumps import PumpSpec, validate_pump_use
from aabflow.water.roster import Closure, ResolvedSupply, WindowCap, resolve_supply, window_cap
from aabflow.water.validation import Residuals, exceeds, tol

LEDGER_VERSION = "aabflow-ledger-1.0.0"


def order_events(events: Iterable[LedgerEvent]) -> list[LedgerEvent]:
    return sorted(events, key=sort_key)


# --------------------------------------------------------------------------- season context


@dataclass
class SeasonContext:
    pilot: PilotData
    season: Season
    crop: CropProfile
    windows: dict[str, RosterWindow]
    windows_by_field: dict[str, list[RosterWindow]]
    supply_profiles: dict[str, SupplyProfile]
    resolved: dict[str, ResolvedSupply]
    weather: dict[str, WeatherScenario]
    weather_daily: dict[str, dict[date, tuple[float, float]]]
    configs: dict[str, SharedConfiguration]
    downtime: dict[str, list[Closure]]
    excluded_instances: dict[str, str]
    intervals: list[AtomicInterval]
    decision_at: datetime
    ponds: dict[str, PondSpec] = field(default_factory=dict)  # existing + admissible proposed
    pond_instance: dict[str, str] = field(default_factory=dict)  # pond asset id -> instance id
    pumps: dict[str, PumpSpec] = field(default_factory=dict)
    leveling: dict[str, tuple[str, float]] = field(default_factory=dict)  # field -> (instance, eff)
    _caps: dict[tuple, WindowCap] = field(default_factory=dict)

    @property
    def planting(self) -> date:
        assert self.season.planting_date is not None
        return self.season.planting_date

    @property
    def days(self) -> list[date]:
        s, e = self.season.sim_start, self.season.sim_end
        return [s + timedelta(days=i) for i in range((e - s).days + 1)]

    def state_ids(self) -> list[str]:
        return [scenarios.state_id(w, s) for w in self.weather for s in self.supply_profiles]

    def typical_state_id(self) -> str:
        typ = next(w for w, ws in self.weather.items() if ws.is_typical)
        return scenarios.state_id(typ, scenarios.NOMINAL)

    def split_state(self, state_id: str) -> tuple[str, str]:
        w, s = state_id.split("__", 1)
        if w not in self.weather or s not in self.supply_profiles:
            raise KeyError(f"unknown state {state_id}")
        return w, s

    def field_node(self, field_id: str) -> str:
        return self.pilot.fields[field_id].outlet_node_id

    def cap(
        self,
        window_id: str,
        supply: ResolvedSupply,
        config_id: str,
        extra_closures: tuple[Closure, ...] = (),
    ) -> WindowCap:
        key = (window_id, supply.resolved_hash, config_id, extra_closures)
        if key not in self._caps:
            w = self.windows[window_id]
            cfg = self.configs[config_id]
            self._caps[key] = window_cap(
                w,
                self.field_node(w.field_id),
                self.pilot.network,
                supply,
                factor_overrides=cfg.edge_delivery_factors,
                extra_closures=tuple(self.downtime.get(config_id, ())) + extra_closures,
                boundaries=[i.start for i in self.intervals],
            )
        return self._caps[key]


def _pond_from_asset(a) -> PondSpec | None:
    if a.usable_capacity_m3 is None or a.surface_area_m2 is None:
        return None
    return PondSpec(
        asset_id=a.asset_id,
        usable_capacity_m3=a.usable_capacity_m3,
        surface_area_m2=a.surface_area_m2,
        initial_inventory_m3=a.initial_inventory_m3,
        k_evap=a.k_evap,
        rain_capture_fraction=a.rain_capture_fraction,
        seepage_m3_day=a.seepage_m3_day,
        max_fill_m3_day=a.max_fill_m3_day,
        max_release_m3_day=a.max_release_m3_day,
        footprint_m2=a.footprint_m2 or 0.0,
        existing=a.existing,
        commissioned_on=a.commissioned_at,
    )


def build_season_context(pilot: PilotData, season_id: str) -> SeasonContext:
    season = crop_profiles.season(season_id)
    crop = crop_profiles.profile(season.crop_profile_id)
    windows_list = pilot.roster.get(season_id, [])
    if not windows_list:
        raise ValueError(f"{pilot.pilot_id} roster has no windows for {season_id}")
    windows = {w.window_id: w for w in windows_list}
    by_field: dict[str, list[RosterWindow]] = defaultdict(list)
    for w in sorted(windows_list, key=lambda w: (to_utc(w.start), w.window_id)):
        if w.field_id not in pilot.fields:
            raise ValueError(f"window {w.window_id} references unknown field {w.field_id}")
        by_field[w.field_id].append(w)
    weather = {w.weather_scenario_id: w for w in scenarios.load_weather_scenarios(season_id, pilot.pilot_id)}
    wdaily = {wid: scenarios.weather_daily(ws.transformed_sha256) for wid, ws in weather.items()}
    try:
        profs = scenarios.load_supply_profiles(season_id, pilot.pilot_id)
    except Exception:  # noqa: BLE001
        profs = scenarios.supply_profiles(season, scenarios.generic_base_hash(season))
    if not any(True for _ in profs):
        raise ValueError("no supply profiles")
    sp = {p.supply_profile_id: p for p in profs}
    resolved = {k: resolve_supply(v) for k, v in sp.items()}
    decision_at = season.decision_at or local_midnight_utc(season.sim_start)
    configs, downtime_raw, excluded = configurations(pilot, decision_at, season.planting_date)
    downtime = {
        cid: [Closure(a, b, frozenset({eid}), f"downtime:{eid}") for eid, a, b in cl]
        for cid, cl in downtime_raw.items()
    }
    # Atomic interval boundaries: windows, closures, capacity changes, supply closures,
    # commissioning/downtime, horizon (T4.1).
    h0 = local_midnight_utc(season.sim_start)
    h1 = local_midnight_utc(season.sim_end + timedelta(days=1))
    bounds: list[datetime] = []
    for w in windows_list:
        bounds += [to_utc(w.start), to_utc(w.end)]
    for e in pilot.edges:
        for c in e.capacities:
            bounds += [to_utc(c.start), to_utc(c.end)]
        for c0, c1 in e.closures:
            bounds += [to_utc(c0), to_utc(c1)]
    for r in resolved.values():
        for c in r.closures:
            bounds += [c.start, c.end]
    for cl in downtime.values():
        for c in cl:
            bounds += [c.start, c.end]
    ctx = SeasonContext(
        pilot=pilot,
        season=season,
        crop=crop,
        windows=windows,
        windows_by_field=dict(by_field),
        supply_profiles=sp,
        resolved=resolved,
        weather=weather,
        weather_daily=wdaily,
        configs={c.shared_configuration_id: c for c in configs},
        downtime=downtime,
        excluded_instances=dict(excluded),
        intervals=[],
        decision_at=decision_at,
    )
    # Assets
    for a in pilot.assets.values():
        if a.kind is AssetKind.pond and a.existing:
            spec = _pond_from_asset(a)
            if spec is None:
                ctx.excluded_instances[a.asset_id] = "existing pond lacks capacity/surface area"
                continue
            asset_available_on(a)
            ctx.ponds[a.asset_id] = spec
        elif a.kind is AssetKind.pump and a.existing:
            try:
                asset_available_on(a)
                ctx.pumps[a.asset_id] = PumpSpec.from_asset(a)
            except Exception as exc:  # noqa: BLE001
                ctx.excluded_instances[a.asset_id] = str(exc)
    for inst in sorted(pilot.instances.values(), key=lambda i: i.instance_id):
        if inst.category is ActionCategory.shared_repair:
            continue
        why = instance_admissibility(inst, decision_at, season.planting_date, pilot)
        if why:
            ctx.excluded_instances[inst.instance_id] = why
            continue
        if inst.category is ActionCategory.pond:
            p = inst.parameters
            try:
                spec = PondSpec(
                    asset_id=f"pond@{inst.instance_id}",
                    usable_capacity_m3=float(p["usable_capacity_m3"]),
                    surface_area_m2=float(p["surface_area_m2"]),
                    initial_inventory_m3=0.0,  # new ponds start empty
                    k_evap=float(p.get("k_evap", 1.0)),
                    rain_capture_fraction=float(p.get("rain_capture_fraction", 1.0)),
                    seepage_m3_day=float(p.get("seepage_m3_day", 0.0)),
                    max_fill_m3_day=p.get("max_fill_m3_day"),
                    max_release_m3_day=p.get("max_release_m3_day"),
                    footprint_m2=float(p["footprint_m2"]),
                    existing=False,
                    commissioned_on=commissioned_on(inst, decision_at),
                )
            except (KeyError, ValueError, TypeError) as exc:
                ctx.excluded_instances[inst.instance_id] = f"pond parameters invalid: {exc}"
                continue
            ctx.ponds[spec.asset_id] = spec
            ctx.pond_instance[spec.asset_id] = inst.instance_id
        elif inst.category is ActionCategory.leveling:
            eff = inst.parameters.get("application_efficiency_after")
            if eff is None:
                ctx.excluded_instances[inst.instance_id] = "leveling lacks application_efficiency_after"
                continue
            for fid in inst.target_ids:
                ctx.leveling[fid] = (inst.instance_id, units.fraction(float(eff), "application_efficiency"))
        elif inst.category is ActionCategory.pump_supplement:
            for tid in inst.target_ids:
                if tid in ctx.pumps and ctx.pumps[tid].cost_per_m3_pkr is None:
                    ctx.excluded_instances[inst.instance_id] = f"pump {tid} has no declared cost per m3"
    for spec in ctx.ponds.values():
        if spec.commissioned_on:
            bounds.append(local_midnight_utc(spec.commissioned_on))
    ctx.intervals = atomic_intervals(bounds, (h0, h1))
    return ctx


@lru_cache(maxsize=16)
def _cached_context(pilot_id: str, pilot_version: str, season_id: str) -> SeasonContext:
    return build_season_context(load_pilot(pilot_id, pilot_version), season_id)


def season_context(pilot_id: str, season_id: str, pilot_version: str | None = None) -> SeasonContext:
    from aabflow.water.context import latest_version

    return _cached_context(pilot_id, pilot_version or latest_version(pilot_id), season_id)


# --------------------------------------------------------------------------- per-policy evaluation


def pond_field_ids(ctx: SeasonContext, asset_id: str) -> list[str]:
    if asset_id in ctx.pilot.assets:
        return list(ctx.pilot.assets[asset_id].field_ids)
    inst = ctx.pilot.instances[ctx.pond_instance[asset_id]]
    return list(inst.target_ids)


@dataclass
class PolicyEvaluation:
    outcome_events: list[LedgerEvent]  # field-level events (receipts, pond incl. exogenous, pump, application)
    routed: dict[tuple[str, str], float]  # (resource_id, interval_id) -> volume
    residuals: Residuals
    canal_receipt_m3: float
    groundwater_m3: float
    pond_loss_m3: float = 0.0
    pond_spill_m3: float = 0.0
    pond_rain_m3: float = 0.0
    terminal_pond_m3: float = 0.0
    peak_pond_m3: dict[str, float] = field(default_factory=dict)


def evaluate_events(
    policy: CandidatePolicy,
    ctx: SeasonContext,
    supply: ResolvedSupply,
    weather_scenario_id: str,
    config_id: str,
    extra_closures: tuple[Closure, ...] = (),
) -> PolicyEvaluation:
    r = Residuals()
    fid = policy.field_id
    if fid not in ctx.pilot.fields:
        r.fail("area", 0, [fid], detail=f"field {fid} not in pilot version {ctx.pilot.pilot_version}")
        return PolicyEvaluation([], {}, r, 0, 0)
    if policy.shared_configuration_id != config_id:
        r.fail("event_order", 0, [policy.candidate_policy_id], detail="policy belongs to another configuration")
    f = ctx.pilot.fields[fid]
    events: list[LedgerEvent] = []
    routed: dict[tuple[str, str], float] = defaultdict(float)
    ivl = {(to_utc(i.start), to_utc(i.end)): i.interval_id for i in ctx.intervals}
    planting = ctx.planting
    # ---- area (T4.4)
    r.check("area")
    new_ponds = [a for a in policy.uses_asset_ids if a in ctx.pond_instance]
    footprint = sum(ctx.ponds[a].footprint_m2 for a in new_ponds)
    try:
        expect_area = units.cropped_area_ha(f.gross_area_ha, footprint)
        if abs(expect_area - policy.cropped_area_ha) > 1e-9:
            r.fail("area", abs(expect_area - policy.cropped_area_ha), [fid], unit="ha",
                   detail=f"cropped area {policy.cropped_area_ha} != gross - new pond footprint {expect_area}")
    except units.UnitError as exc:
        r.fail("area", 0, [fid], unit="ha", detail=str(exc))
    # ---- instances: admissibility, costs, commissioning (T4.6)
    r.check("commissioning")
    r.check("cost_completeness")
    for iid in policy.required_instance_ids:
        inst = ctx.pilot.instances.get(iid)
        if inst is None:
            r.fail("commissioning", 0, [iid], detail=f"instance {iid} not in pilot version")
            continue
        mc = missing_cost(inst)
        if mc:
            r.fail("cost_completeness", 0, [iid], detail=mc)
        why = instance_admissibility(inst, ctx.decision_at, planting, ctx.pilot)
        if why and not mc:
            r.fail("commissioning", 0, [iid], detail=why)
    for a in new_ponds:
        if ctx.pond_instance[a] not in policy.required_instance_ids:
            r.fail("commissioning", 0, [a], detail="new pond used without requiring its instance")
    if policy.application_efficiency != f.existing_application_efficiency:
        lev = ctx.leveling.get(fid)
        if lev is None or lev[0] not in policy.required_instance_ids or lev[1] != policy.application_efficiency:
            r.fail("commissioning", 0, [fid], detail="application efficiency differs without admissible leveling")
    # ---- receipts: rights, route, chronology
    r.check("receipt_right")
    r.check("route_open")
    canal = 0.0
    path = ctx.pilot.network.path_edges(f.outlet_node_id)
    cfg = ctx.configs.get(config_id)
    overrides = cfg.edge_delivery_factors if cfg else {}
    receipts_by_day: dict[date, float] = defaultdict(float)
    for ev in policy.receipt_events:
        events.append(ev)
        if ev.kind is not LedgerEventKind.outlet_receipt or ev.field_id != fid:
            r.fail("receipt_right", ev.volume_m3, [ev.event_id], ev.timestamp, "receipt event malformed")
            continue
        w = ctx.windows.get(ev.window_id or "")
        if w is None or w.field_id != fid:
            r.fail("receipt_right", ev.volume_m3, [ev.event_id, ev.window_id or "?"], ev.timestamp,
                   "receipt outside the field's permitted windows")
            continue
        if to_utc(ev.timestamp) != to_utc(w.end):
            r.fail("receipt_right", ev.volume_m3, [ev.event_id], ev.timestamp,
                   f"receipt must be booked at its window end {w.end.isoformat()}")
        cap = ctx.cap(w.window_id, supply, config_id, extra_closures)
        if ev.volume_m3 > 0 and cap.field_cap_m3 <= 0:
            r.fail("route_open", ev.volume_m3, [ev.event_id, w.window_id, *path], ev.timestamp,
                   f"route closed for window {w.window_id} under {supply.supply_profile_id}")
            continue
        if exceeds(ev.volume_m3, cap.field_cap_m3):
            r.fail("receipt_right", ev.volume_m3 - cap.field_cap_m3, [ev.event_id, w.window_id], ev.timestamp,
                   f"receipt {ev.volume_m3:.2f} m3 exceeds window cap {cap.field_cap_m3:.2f} m3 "
                   f"under {supply.supply_profile_id}")
        canal += ev.volume_m3
        receipts_by_day[local_crop_date(ev.timestamp)] += ev.volume_m3
        for piece, vol in cap.split(ev.volume_m3):
            legs = ctx.pilot.network.route(vol, path, overrides)
            iid = ivl.get((piece.start, piece.end))
            if iid is None:
                r.fail("event_order", vol, [w.window_id], piece.start, "window piece not an atomic interval")
                continue
            routed[(f"outlet:{f.outlet_node_id}", iid)] += vol
            for leg in legs:
                routed[(f"edge:{leg.edge_id}", iid)] += leg.intake_m3
            if legs:
                routed[(f"source:{ctx.pilot.network.root_of(f.outlet_node_id)}", iid)] += legs[0].intake_m3
    # ---- ponds
    fills_by_day: dict[date, float] = defaultdict(float)
    release_by_day: dict[date, float] = defaultdict(float)
    by_pond: dict[str, list[LedgerEvent]] = defaultdict(list)
    receipt_ts = {(ev.window_id, to_utc(ev.timestamp)): ev.volume_m3 for ev in policy.receipt_events}
    fill_per_receipt: dict[str, float] = defaultdict(float)
    for ev in policy.pond_events:
        if ev.asset_id not in ctx.ponds:
            r.fail("commissioning", ev.volume_m3, [ev.asset_id or "?"], ev.timestamp, "pond not available")
            continue
        if fid not in pond_field_ids(ctx, ev.asset_id):
            r.fail("pond_sharing", ev.volume_m3, [ev.asset_id, fid], ev.timestamp, "field has no access to pond")
        if ev.asset_id not in policy.uses_asset_ids:
            r.fail("pond_sharing", ev.volume_m3, [ev.asset_id], ev.timestamp, "pond use not declared")
        spec = ctx.ponds[ev.asset_id]
        d = local_crop_date(ev.timestamp)
        if spec.commissioned_on and d < spec.commissioned_on:
            r.fail("commissioning", ev.volume_m3, [ev.asset_id], ev.timestamp,
                   f"pond used {d} before commissioning {spec.commissioned_on}")
        if ev.kind is LedgerEventKind.pond_fill:
            key = (ev.window_id, to_utc(ev.timestamp))
            if key not in receipt_ts:
                r.fail("field_balance", ev.volume_m3, [ev.event_id], ev.timestamp,
                       "pond fill without a matching receipt at that instant")
            fill_per_receipt[str(key)] += ev.volume_m3
            if exceeds(fill_per_receipt[str(key)], receipt_ts.get(key, 0.0)):
                r.fail("field_balance", fill_per_receipt[str(key)] - receipt_ts.get(key, 0.0), [ev.event_id],
                       ev.timestamp, "pond fill exceeds the receipt it comes from")
            fills_by_day[d] += ev.volume_m3
        elif ev.kind is LedgerEventKind.pond_release:
            release_by_day[d] += ev.volume_m3
        else:
            r.fail("event_order", ev.volume_m3, [ev.event_id], ev.timestamp, "pond events must be fill/release")
            continue
        by_pond[ev.asset_id].append(ev)
    loss = spill = rain = terminal = 0.0
    peaks: dict[str, float] = {}
    wd = ctx.weather_daily[weather_scenario_id]
    for aid, evs in by_pond.items():
        spec = ctx.ponds[aid]
        exo, trace = exogenous_events(spec, evs, wd, ctx.days, active_from=spec.commissioned_on)
        r.extend(trace.residuals)
        events.extend(evs)
        events.extend(exo)
        loss += trace.totals.get("pond_evaporation", 0) + trace.totals.get("pond_seepage", 0)
        spill += trace.totals.get("pond_spill", 0)
        rain += trace.totals.get("pond_rain", 0)
        terminal += trace.terminal_m3
        peaks[aid] = trace.peak_m3
    # ---- pumps (local view; shared caps checked jointly too)
    gw = 0.0
    pump_by_day: dict[date, float] = defaultdict(float)
    for aid in {e.asset_id for e in policy.pump_events}:
        spec = ctx.pumps.get(aid or "")
        if spec is None:
            r.fail("pump_access", 0, [aid or "?"], detail="pump not an available existing asset")
            continue
        r.extend(validate_pump_use(spec, policy.pump_events))
        if aid not in policy.uses_asset_ids:
            r.fail("pump_access", 0, [aid], detail="pump use not declared")
    for ev in policy.pump_events:
        events.append(ev)
        d = local_crop_date(ev.timestamp)
        pump_by_day[d] += ev.volume_m3
        gw += ev.volume_m3
        if ev.asset_id in ctx.pumps:
            routed[(f"pump:{ev.asset_id}", day_interval_id(d))] += ev.volume_m3
            routed[(f"gw:{ev.asset_id}", "season")] += ev.volume_m3
    for aid, peak in peaks.items():
        routed[(f"pond:{aid}", "season")] += peak
    # ---- field balance and application consistency
    r.check("field_balance")
    r.check("daily_application")
    sched = defaultdict(float)
    for a in policy.application_schedule:
        sched[a.date] += a.gross_depth_mm
    days = set(sched) | set(receipts_by_day) | set(release_by_day) | set(pump_by_day)
    for d in sorted(days):
        water = receipts_by_day[d] - fills_by_day[d] + release_by_day[d] + pump_by_day[d]
        applied = units.depth_mm_to_volume_m3(sched[d], policy.cropped_area_ha)
        if abs(water - applied) > tol(max(water, applied)) + 1e-6 * max(1.0, water):
            r.fail("field_balance", water - applied, [fid], local_midnight_utc(d),
                   f"{d}: water at field {water:.4f} m3 != applied {applied:.4f} m3")
        if applied > 0 and (d < planting or d > ctx.season.sim_end):
            r.fail("daily_application", applied, [fid], local_midnight_utc(d),
                   f"application on {d} outside crop interval")
        if applied > 0:
            events.append(
                LedgerEvent(
                    event_id=f"apply:{fid}:{d.isoformat()}",
                    timestamp=local_midnight_utc(d + timedelta(days=1)),
                    explicit_order=5,
                    kind=LedgerEventKind.field_application,
                    volume_m3=applied,
                    field_id=fid,
                    note=f"{sched[d]:.4f} mm gross on {policy.cropped_area_ha:.6f} ha",
                )
            )
        if sched[d] > ctx.crop.max_daily_irrigation_mm + 1e-9:
            r.fail("daily_application", sched[d], [fid], local_midnight_utc(d),
                   f"{sched[d]:.2f} mm exceeds the field application limit", unit="mm")
    return PolicyEvaluation(
        order_events(events), dict(routed), r, canal, gw, loss, spill, rain, terminal, peaks
    )


def evaluate_policy(
    policy: CandidatePolicy,
    ctx: SeasonContext,
    resolved_supply: ResolvedSupply,
    weather_scenario_id: str,
    config_id: str,
    *,
    crop_outcome_hash: str | None = None,
    yield_kg_ha: float | None = None,
    state_id: str | None = None,
    extra_closures: tuple[Closure, ...] = (),
) -> StateOutcome:
    """Validate one policy under an (ad-hoc) state; null yield when undeliverable."""
    ev = evaluate_events(policy, ctx, resolved_supply, weather_scenario_id, config_id, extra_closures)
    sid = state_id or scenarios.state_id(weather_scenario_id, resolved_supply.supply_profile_id)
    ok = ev.residuals.ok and (yield_kg_ha is not None or not policy.application_schedule or crop_outcome_hash)
    if yield_kg_ha is None and crop_outcome_hash is None:
        # look up the stored outcome for this weather state
        prior = next((o for o in policy.outcomes if o.weather_scenario_id == weather_scenario_id
                      and o.crop_outcome_hash), None)
        if prior is not None:
            crop_outcome_hash, yield_kg_ha = prior.crop_outcome_hash, prior.yield_kg_ha
    ok = ev.residuals.ok and yield_kg_ha is not None
    return StateOutcome(
        state_id=sid,
        deliverable=ok,
        crop_outcome_hash=crop_outcome_hash if ok else None,
        yield_kg_ha=yield_kg_ha if ok else None,
        production_kg=units.production_kg(policy.cropped_area_ha, yield_kg_ha) if ok else None,
        resources=[],
        service_credit_m3=ev.canal_receipt_m3 if ok else 0.0,
        groundwater_m3=ev.groundwater_m3,
        canal_receipt_m3=ev.canal_receipt_m3,
        weather_scenario_id=weather_scenario_id,
        supply_profile_id=resolved_supply.supply_profile_id,
        violations=ev.residuals.reasons()[:10] or ([] if ok else ["no exact crop outcome for this weather state"]),
        pond_loss_m3=ev.pond_loss_m3,
        pond_spill_m3=ev.pond_spill_m3,
        pond_rain_m3=ev.pond_rain_m3,
        terminal_pond_m3=ev.terminal_pond_m3,
    )


def resource_uses(routed: Mapping[tuple[str, str], float]) -> list[ResourceUse]:
    return [
        ResourceUse(resource_id=rid, interval_id=iid, volume_m3=v)
        for (rid, iid), v in sorted(routed.items())
        if v > 0 and not rid.startswith("outlet:")
    ]


# --------------------------------------------------------------------------- capacities


def library_capacities(ctx: SeasonContext) -> list[ResourceCapacity]:
    """Shared-resource upper bounds per atomic interval/state/configuration."""
    out: list[ResourceCapacity] = []
    net = ctx.pilot.network
    for iv in ctx.intervals:
        a, b = to_utc(iv.start), to_utc(iv.end)
        for e in ctx.pilot.edges:
            c = net.capacity_m3(e.edge_id, a, b)
            closed = net.closed_seconds(e.edge_id, a, b) > 0
            if closed:
                out.append(ResourceCapacity(resource_id=f"edge:{e.edge_id}", interval_id=iv.interval_id, capacity_m3=0.0))
            elif c is not None:
                out.append(ResourceCapacity(resource_id=f"edge:{e.edge_id}", interval_id=iv.interval_id, capacity_m3=c))
        for cid, cl in ctx.downtime.items():
            for c in cl:
                if overlap_seconds(a, b, c.start, c.end) > 0:
                    for eid in c.edge_ids:
                        out.append(ResourceCapacity(resource_id=f"edge:{eid}", interval_id=iv.interval_id,
                                                    capacity_m3=0.0, shared_configuration_id=cid))
        roots = {n for n, node in net.nodes.items() if node.kind.value == "source"}
        for w in ctx.weather:
            for sid, rs in ctx.resolved.items():
                for c in rs.closures:
                    if overlap_seconds(a, b, c.start, c.end) <= 0:
                        continue
                    state = scenarios.state_id(w, sid)
                    if c.edge_ids:
                        for eid in c.edge_ids:
                            out.append(ResourceCapacity(resource_id=f"edge:{eid}", interval_id=iv.interval_id,
                                                        capacity_m3=0.0, state_id=state))
                    else:
                        for root in roots:
                            out.append(ResourceCapacity(resource_id=f"source:{root}", interval_id=iv.interval_id,
                                                        capacity_m3=0.0, state_id=state))
    for p in ctx.pumps.values():
        for d in ctx.days:
            if p.commissioned_on and d < p.commissioned_on:
                cap = 0.0
            else:
                cap = p.daily_cap_m3
            out.append(ResourceCapacity(resource_id=f"pump:{p.asset_id}", interval_id=day_interval_id(d), capacity_m3=cap))
        if p.seasonal_cap_m3 is not None:
            out.append(ResourceCapacity(resource_id=f"gw:{p.asset_id}", interval_id="season", capacity_m3=p.seasonal_cap_m3))
    for spec in ctx.ponds.values():
        out.append(ResourceCapacity(resource_id=f"pond:{spec.asset_id}", interval_id="season",
                                    capacity_m3=spec.usable_capacity_m3))
    return out


# --------------------------------------------------------------------------- reconstruct


def load_policies(library: CandidateLibrary) -> dict[str, CandidatePolicy]:
    from aabflow.science.paths import libraries_dir

    path = libraries_dir() / library.policies_ref
    out = {}
    with path.open() as fh:
        for line in fh:
            if line.strip():
                p = CandidatePolicy.model_validate_json(line)
                out[p.candidate_policy_id] = p
    return out


@lru_cache(maxsize=8)
def _policies_cached(library_hash: str, policies_ref: str) -> dict[str, CandidatePolicy]:
    from aabflow.science.paths import libraries_dir

    out = {}
    with (libraries_dir() / policies_ref).open() as fh:
        for line in fh:
            if line.strip():
                p = CandidatePolicy.model_validate_json(line)
                out[p.candidate_policy_id] = p
    return out


def reconstruct(
    policy_ids: list[str],
    library: CandidateLibrary,
    state_id: str,
    config_id: str,
    *,
    resolved_supply: ResolvedSupply | None = None,
    extra_closures: tuple[Closure, ...] = (),
    ctx: SeasonContext | None = None,
    policies: Mapping[str, CandidatePolicy] | None = None,
    check_crop_outcomes: bool = True,
) -> tuple[list[LedgerEvent], PhysicalValidationReport]:
    """Rebuild and validate a selected plan's full ledger at original precision (T6.6)."""
    ctx = ctx or season_context(library.pilot_id, library.season_id, library.pilot_version)
    pols = policies or _policies_cached(library.candidate_library_hash, library.policies_ref)
    r = Residuals()
    weather_id, supply_id = ctx.split_state(state_id)
    supply = resolved_supply or ctx.resolved[supply_id]
    if config_id not in ctx.configs:
        r.fail("event_order", 0, [config_id], detail=f"unknown shared configuration {config_id}")
        return [], r.report()
    events: list[LedgerEvent] = []
    routed_total: dict[tuple[str, str], float] = defaultdict(float)
    pump_events: list[LedgerEvent] = []
    seen_fields: dict[str, str] = {}
    pond_users: dict[str, list[str]] = defaultdict(list)
    r.check("pond_sharing")
    from aabflow.science.experiments import load_outcome

    for pid in policy_ids:
        p = pols.get(pid)
        if p is None:
            r.fail("event_order", 0, [pid], detail=f"policy {pid} not in library {library.candidate_library_hash[:12]}")
            continue
        if p.field_id in seen_fields:
            r.fail("receipt_right", 0, [p.field_id, pid, seen_fields[p.field_id]], detail="two policies for one field")
        seen_fields[p.field_id] = pid
        ev = evaluate_events(p, ctx, supply, weather_id, config_id, extra_closures)
        r.extend(ev.residuals)
        events.extend(ev.outcome_events)
        pump_events.extend(p.pump_events)
        for k, v in ev.routed.items():
            routed_total[k] += v
        for aid in ev.peak_pond_m3:
            pond_users[aid].append(p.field_id)
        # exact crop outcome for the weather state
        so = next((o for o in p.outcomes if o.weather_scenario_id == weather_id and o.crop_outcome_hash), None)
        if check_crop_outcomes and (p.application_schedule or so is not None):
            r.check("daily_application")
            if so is None:
                r.fail("daily_application", 0, [pid], detail=f"no exact crop outcome for weather {weather_id}")
            else:
                co = load_outcome(so.crop_outcome_hash)
                if co is None or not co.has_finished:
                    r.fail("daily_application", 0, [pid], detail="crop outcome artifact missing or unfinished")
                elif abs(co.seasonal_irrigation_mm - sum(a.gross_depth_mm for a in p.application_schedule)) > 1e-6:
                    r.fail("daily_application", co.seasonal_irrigation_mm, [pid],
                           detail="crop outcome irrigation differs from the policy schedule", unit="mm")
    for aid, users in pond_users.items():
        if len(set(users)) > 1:
            spec = ctx.ponds[aid]
            if exceeds(routed_total[(f"pond:{aid}", "season")], spec.usable_capacity_m3):
                r.fail("pond_sharing", routed_total[(f"pond:{aid}", "season")] - spec.usable_capacity_m3,
                       [aid, *users], detail="combined peak reservations exceed the shared pond")
    # shared pumps across all fields
    for aid, spec in ctx.pumps.items():
        r.extend(validate_pump_use(spec, pump_events))
        r.check("pump_sharing")
    # capacities
    caps = library_capacities(ctx)
    r.check("edge_capacity")
    r.check("source_capacity")
    for c in caps:
        if c.state_id not in (None, state_id) or c.shared_configuration_id not in (None, config_id):
            continue
        if c.resource_id.startswith(("pump:", "gw:", "pond:")):
            continue  # validated by pump/pond rules above
        used = routed_total.get((c.resource_id, c.interval_id), 0.0)
        if exceeds(used, c.capacity_m3):
            rule = "source_capacity" if c.resource_id.startswith("source:") else "edge_capacity"
            r.fail(rule, used - c.capacity_m3, [c.resource_id, c.interval_id],
                   next((i.start for i in ctx.intervals if i.interval_id == c.interval_id), None),
                   f"{used:.2f} m3 through {c.resource_id} exceeds {c.capacity_m3:.2f} m3")
    # routed network events + node balance
    events.extend(_network_events(ctx, routed_total, config_id, r))
    return order_events(events), r.report()


def _network_events(
    ctx: SeasonContext, routed: Mapping[tuple[str, str], float], config_id: str, r: Residuals
) -> list[LedgerEvent]:
    net = ctx.pilot.network
    overrides = ctx.configs[config_id].edge_delivery_factors
    ivmap = {i.interval_id: i for i in ctx.intervals}
    out: list[LedgerEvent] = []
    r.check("node_balance")
    by_iv: dict[str, dict[str, float]] = defaultdict(dict)
    for (rid, iid), v in routed.items():
        if rid.startswith("edge:"):
            by_iv[iid][rid[5:]] = v
        elif rid.startswith("source:"):
            iv = ivmap[iid]
            out.append(LedgerEvent(event_id=f"src:{rid[7:]}:{iid}", timestamp=iv.end, explicit_order=-3,
                                   kind=LedgerEventKind.source_release, volume_m3=v, note=f"interval {iid}"))
    for iid, flows in by_iv.items():
        iv = ivmap[iid]
        for eid, intake in flows.items():
            delivered = intake * net.factor(eid, overrides)
            out.append(LedgerEvent(event_id=f"edge:{eid}:{iid}", timestamp=iv.end, explicit_order=-2,
                                   kind=LedgerEventKind.edge_transfer, volume_m3=intake, edge_id=eid))
            out.append(LedgerEvent(event_id=f"loss:{eid}:{iid}", timestamp=iv.end, explicit_order=-1,
                                   kind=LedgerEventKind.edge_loss, volume_m3=intake - delivered, edge_id=eid))
        # node balance: delivered by incoming edge == sum(child intakes) + outlet receipts at node
        for eid, intake in flows.items():
            e = net.edges[eid]
            delivered = intake * net.factor(eid, overrides)
            child = sum(flows.get(c, 0.0) for c in net.children.get(e.downstream_node_id, []))
            local = routed.get((f"outlet:{e.downstream_node_id}", iid), 0.0)
            resid = delivered - child - local
            if abs(resid) > tol(delivered):
                r.fail("node_balance", resid, [e.downstream_node_id, iid], iv.start,
                       f"node {e.downstream_node_id}: delivered {delivered:.6f} != downstream "
                       f"{child:.6f} + outlet {local:.6f}")
    return out


def describe_rules() -> dict[str, Any]:
    return {"version": LEDGER_VERSION, "ordering": "(timestamp, explicit_order, event_id)"}


def json_events(events: list[LedgerEvent]) -> str:
    return json.dumps([e.model_dump(mode="json") for e in events])


__all__ = [
    "PKT",
    "SeasonContext",
    "build_season_context",
    "evaluate_events",
    "evaluate_policy",
    "library_capacities",
    "order_events",
    "reconstruct",
    "resource_uses",
    "season_context",
]
