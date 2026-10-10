"""Candidate policy generation and immutable candidate libraries (T5.5-T5.7, T6.5).

For every field and admissible shared-repair configuration the generator
builds complete dated physical decisions (receipts per roster window, pond
fills/releases, pump top-ups, application schedule) from templates, validates
them through the ledger in every uncertainty state, obtains exact crop
outcomes by ``crop_experiment_hash`` (running AquaCrop when absent), removes
only *safely* dominated options and publishes:

    data/libraries/<pilot>/<season>/<library_hash>/library.json   (CandidateLibrary)
    data/libraries/<pilot>/<season>/<library_hash>/policies.jsonl (CandidatePolicy)
    data/libraries/<pilot>/<season>/latest.json

Families (``CandidatePolicy.family``):

* ``rainfed`` - mandatory zero-receipt policy, deliverable in every state;
* ``baseline_B0`` - the fixed-roster operating habit (one per supply profile,
  because B0 is processed through the same curtailment/closures as other
  plans): irrigate on receipt in every turn from planting to DAP
  ``B0_STOP_DAP`` regardless of crop stage; an existing pond is filled only from
  pre-planting turns and released only after 21 days without water; no pumping;
* ``full_window`` (per supply profile), ``deficit`` (50/75% of each turn),
  ``skip_*`` (phase skips), ``alternate_*``, ``critical_only``;
* ``robust`` - receipts sized to the smallest cap across supply states, so
  the policy is deliverable in every supply state;
* ``pond_shift`` / ``pond_full`` - existing or new pond storing early/pre-plant
  turns and releasing at critical stages (incl. during the interruption);
* ``pump_topup`` - existing shared pump top-ups at critical stages;
* every irrigating family may additionally carry leveling (raised AppEff).

Experiment reuse: crop runs depend on (crop, soil, AppEff, dated depth
schedule, weather) only, never on the field; identical schedules across fields
or configurations hit the experiment cache.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from aabflow.domain import units
from aabflow.domain.calendar import PKT, local_crop_date, to_utc
from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import (
    CandidateLibrary,
    CandidatePolicy,
    Crop,
    CropExperiment,
    IrrigationEvent,
    LedgerEvent,
    LedgerEventKind,
    LibraryCoverage,
    StateOutcome,
)
from aabflow.science import scenarios
from aabflow.science.adapter import ADAPTER_VERSION
from aabflow.science.experiments import crop_experiment_hash, make_experiment, run_batch
from aabflow.science.paths import atomic_write_text, libraries_dir
from aabflow.water.context import load_pilot
from aabflow.water.ledger import (
    SeasonContext,
    build_season_context,
    evaluate_events,
    library_capacities,
    resource_uses,
)
from aabflow.water.pond import PondSpec, exogenous_events

GENERATOR_VERSION = "aabflow-candidates-1.0.0"
DEPTH_GRID_MM = 0.1
TEMPLATE_STOP_DAP = {Crop.wheat: 120, Crop.cotton: 150}
B0_STOP_DAP = {Crop.wheat: 135, Crop.cotton: 165}
B0_POND_DRY_DAYS = 21
CRITICAL_DAP = {Crop.wheat: [(55, 80), (85, 115)], Crop.cotton: [(55, 95), (95, 135)]}
RELEASE_DAP = {Crop.wheat: [72, 93, 100, 108], Crop.cotton: [70, 79, 86, 105]}
PUMP_DAP = {Crop.wheat: [68, 95, 102], Crop.cotton: [78, 87, 110]}
PUMP_DEPTH_MM = 40.0
RELEASE_DEPTH_MM = 60.0
MAX_TRUNCATION_ROUNDS = 4


class CandidateError(RuntimeError):
    pass


# --------------------------------------------------------------------------- templates


@dataclass
class Template:
    family: str
    tags: list[str]
    field_id: str
    config_id: str
    app_eff: float
    area_ha: float
    receipts_direct_mm: dict[str, float] = field(default_factory=dict)  # window -> direct depth
    fills_m3: dict[str, float] = field(default_factory=dict)  # window -> fill volume
    releases_mm: list[tuple[date, float]] = field(default_factory=list)
    pumps_mm: list[tuple[date, float]] = field(default_factory=list)
    pond: PondSpec | None = None
    pump_id: str | None = None
    instances: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    truncated_after: date | None = None

    def key(self) -> str:
        return content_hash(
            {
                "f": self.field_id,
                "c": self.config_id,
                "e": self.app_eff,
                "a": self.area_ha,
                "r": sorted(self.receipts_direct_mm.items()),
                "fi": sorted(self.fills_m3.items()),
                "rel": self.releases_mm,
                "p": self.pumps_mm,
                "pond": self.pond.asset_id if self.pond else None,
                "pump": self.pump_id,
                "i": sorted(self.instances),
                "t": self.truncated_after,
            }
        )


def floor_grid(x: float, grid: float = DEPTH_GRID_MM) -> float:
    return max(0.0, int(x / grid + 1e-9) * grid)


def at_local(d: date, hour: int) -> datetime:
    return to_utc(datetime(d.year, d.month, d.day, hour, tzinfo=PKT))


@dataclass
class FieldView:
    field_id: str
    soil_profile_id: str
    gross_area_ha: float
    app_eff: float
    windows: list[str]  # window ids sorted
    end_date: dict[str, date]
    dap: dict[str, int]
    cap: dict[str, dict[str, float]]  # supply_id -> window -> field cap m3
    pond_assets: list[str]
    new_ponds: list[str]
    pump_ids: list[str]
    leveling: tuple[str, float] | None


def field_view(ctx: SeasonContext, fid: str, config_id: str) -> FieldView:
    f = ctx.pilot.fields[fid]
    ws = ctx.windows_by_field.get(fid, [])
    end_date = {w.window_id: local_crop_date(w.end) for w in ws}
    dap = {wid: (d - ctx.planting).days for wid, d in end_date.items()}
    cap = {
        sid: {w.window_id: ctx.cap(w.window_id, rs, config_id).field_cap_m3 for w in ws}
        for sid, rs in ctx.resolved.items()
    }
    ponds = [a for a, s in ctx.ponds.items() if s.existing and fid in ctx.pilot.assets[a].field_ids]
    new = [a for a, iid in ctx.pond_instance.items() if fid in ctx.pilot.instances[iid].target_ids]
    pumps = [
        p for p, s in ctx.pumps.items() if fid in s.field_ids and s.cost_per_m3_pkr is not None
    ]
    return FieldView(
        fid,
        f.soil_profile_id,
        f.gross_area_ha,
        f.existing_application_efficiency,
        [w.window_id for w in ws],
        end_date,
        dap,
        cap,
        ponds,
        new,
        pumps,
        ctx.leveling.get(fid),
    )


def _direct(fv: FieldView, wid: str, take_m3: float, area: float, max_mm: float) -> float:
    return floor_grid(min(take_m3 / (area * 10.0), max_mm))


def make_templates(ctx: SeasonContext, fv: FieldView, config_id: str) -> list[Template]:
    crop = ctx.season.crop
    max_mm = ctx.crop.max_daily_irrigation_mm
    stop = TEMPLATE_STOP_DAP[crop]
    out: list[Template] = []
    nominal, short, intr = scenarios.NOMINAL, scenarios.SHORTAGE, scenarios.INTERRUPTION
    sids = [s for s in (nominal, short, intr) if s in fv.cap] or list(fv.cap)
    in_season = [w for w in fv.windows if 0 <= fv.dap[w] <= stop]

    def tpl(family, tags, area=None, eff=None, **kw) -> Template:
        return Template(
            family,
            tags,
            fv.field_id,
            config_id,
            eff or fv.app_eff,
            area if area is not None else fv.gross_area_ha,
            **kw,
        )

    def take(sid: str, wids: Iterable[str], frac: float = 1.0, area=None) -> dict[str, float]:
        a = area if area is not None else fv.gross_area_ha
        res = {}
        for w in wids:
            mm = _direct(fv, w, fv.cap[sid][w] * frac, a, max_mm)
            if mm > 0:
                res[w] = mm
        return res

    min_cap = {w: min(fv.cap[s][w] for s in sids) for w in fv.windows}

    def take_robust(wids, area=None) -> dict[str, float]:
        a = area if area is not None else fv.gross_area_ha
        return {w: mm for w in wids if (mm := floor_grid(min(min_cap[w] / (a * 10), max_mm))) > 0}

    # mandatory zero-receipt
    out.append(tpl("rainfed", ["rainfed", "zero_receipt"]))
    # B0 habit per supply profile
    b0_stop = B0_STOP_DAP[crop]
    b0_w = [w for w in fv.windows if 0 <= fv.dap[w] <= b0_stop]
    for sid in sids:
        t = tpl("baseline_B0", ["baseline", f"supply:{sid}"], receipts_direct_mm=take(sid, b0_w))
        t.params = {
            "rule": f"irrigate on receipt every turn to DAP {b0_stop}; pond from pre-plant "
            f"turns, released after {B0_POND_DRY_DAYS} dry days; no pumping",
            "supply": sid,
        }
        if fv.pond_assets:
            _b0_pond(ctx, fv, t, ctx.ponds[fv.pond_assets[0]], sid)
        out.append(t)
    effs: list[tuple[float, list[str], str]] = [(fv.app_eff, [], "")]
    if fv.leveling:
        effs.append((fv.leveling[1], [fv.leveling[0]], "+leveling"))
    for eff, inst, suffix in effs:
        tags = ["leveling"] if inst else []
        for sid in sids:
            out.append(
                tpl(
                    "full_window" + suffix,
                    ["full_window", f"supply:{sid}", *tags],
                    eff=eff,
                    receipts_direct_mm=take(sid, in_season),
                    instances=list(inst),
                )
            )
        out.append(
            tpl(
                "robust" + suffix,
                ["robust", *tags],
                eff=eff,
                receipts_direct_mm=take_robust(in_season),
                instances=list(inst),
            )
        )
        out.append(
            tpl(
                "deficit" + suffix,
                ["deficit", "frac:0.75", *tags],
                eff=eff,
                receipts_direct_mm=take(nominal, in_season, 0.75),
                instances=list(inst),
            )
        )
        if not inst:
            out.append(
                tpl(
                    "deficit",
                    ["deficit", "frac:0.5"],
                    receipts_direct_mm=take(nominal, in_season, 0.5),
                )
            )
            out.append(
                tpl(
                    "skip_early",
                    ["timing", "skip:<30"],
                    receipts_direct_mm=take(nominal, [w for w in in_season if fv.dap[w] >= 30]),
                )
            )
            out.append(
                tpl(
                    "skip_mid",
                    ["timing", "skip:30-70"],
                    receipts_direct_mm=take(
                        nominal, [w for w in in_season if not 30 <= fv.dap[w] < 70]
                    ),
                )
            )
            out.append(
                tpl(
                    "skip_late",
                    ["timing", "skip:>90"],
                    receipts_direct_mm=take(nominal, [w for w in in_season if fv.dap[w] <= 90]),
                )
            )
            out.append(
                tpl(
                    "alternate_even",
                    ["timing", "alternate"],
                    receipts_direct_mm=take(nominal, in_season[0::2]),
                )
            )
            out.append(
                tpl(
                    "alternate_odd",
                    ["timing", "alternate"],
                    receipts_direct_mm=take(nominal, in_season[1::2]),
                )
            )
            crit = [w for w in in_season if any(a <= fv.dap[w] <= b for a, b in CRITICAL_DAP[crop])]
            out.append(
                tpl("critical_only", ["timing", "critical"], receipts_direct_mm=take(nominal, crit))
            )
            # depth variants and shortage-safe timing variants (deliverable under 22% curtailment)
            for frac in (0.6, 0.9):
                out.append(
                    tpl(
                        "deficit",
                        ["deficit", f"frac:{frac}"],
                        receipts_direct_mm=take(nominal, in_season, frac),
                    )
                )
            sh = short if short in fv.cap else nominal
            out.append(
                tpl(
                    "skip_early",
                    ["timing", "skip:<30", f"supply:{sh}"],
                    receipts_direct_mm=take(sh, [w for w in in_season if fv.dap[w] >= 30]),
                )
            )
            out.append(
                tpl(
                    "skip_late",
                    ["timing", "skip:>90", f"supply:{sh}"],
                    receipts_direct_mm=take(sh, [w for w in in_season if fv.dap[w] <= 90]),
                )
            )
            out.append(
                tpl(
                    "critical_only",
                    ["timing", "critical", "robust"],
                    receipts_direct_mm=take_robust(crit),
                )
            )
            out.append(
                tpl(
                    "alternate_even",
                    ["timing", "alternate", "robust"],
                    receipts_direct_mm=take_robust(in_season[0::2]),
                )
            )
            early_stop = [w for w in in_season if fv.dap[w] <= stop - 20]
            out.append(
                tpl(
                    "early_stop",
                    ["timing", f"stop:{stop - 20}"],
                    receipts_direct_mm=take(nominal, early_stop),
                )
            )
        # pump top-ups
        for pid in fv.pump_ids:
            spec = ctx.pumps[pid]
            for sid_base, days, fam in (
                (nominal, PUMP_DAP[crop][:2], "pump_topup"),
                (short, PUMP_DAP[crop], "pump_topup"),
                ("robust", PUMP_DAP[crop][1:], "pump_robust"),
            ):
                rec = take_robust(in_season) if sid_base == "robust" else take(sid_base, in_season)
                t = tpl(
                    fam + suffix,
                    ["pump", f"supply:{sid_base}", *tags],
                    eff=eff,
                    receipts_direct_mm=rec,
                    instances=list(inst),
                    pump_id=pid,
                )
                for dp in days:
                    d = ctx.planting + timedelta(days=dp)
                    mm = floor_grid(min(PUMP_DEPTH_MM, spec.daily_cap_m3 / (fv.gross_area_ha * 10)))
                    if mm > 0:
                        t.pumps_mm.append((d, mm))
                out.append(t)
        # ponds: existing and new (cropped area shrinks by a new pond's footprint)
        for aid in fv.pond_assets + fv.new_ponds:
            spec = ctx.ponds[aid]
            new = aid in fv.new_ponds
            area = (
                units.cropped_area_ha(fv.gross_area_ha, spec.footprint_m2)
                if new
                else fv.gross_area_ha
            )
            pinst = [ctx.pond_instance[aid]] if new else []
            pre = [w for w in fv.windows if fv.dap[w] < 0]
            early = [w for w in in_season if fv.dap[w] < 40]
            for fam, fill_from, rec_fn, rel in (
                (
                    "pond_full",
                    pre,
                    lambda a: take(nominal, in_season, area=a),
                    RELEASE_DAP[crop][:2],
                ),
                (
                    "pond_shift",
                    pre + early,
                    lambda a: take(nominal, in_season, area=a),
                    RELEASE_DAP[crop][1:],
                ),
                (
                    "pond_robust",
                    pre + early,
                    lambda a: take_robust(in_season, area=a),
                    RELEASE_DAP[crop][1:3],
                ),
            ):
                t = tpl(
                    fam + suffix,
                    ["pond", "new_pond" if new else "existing_pond", *tags],
                    area=area,
                    eff=eff,
                    receipts_direct_mm=rec_fn(area),
                    instances=list(inst) + pinst,
                    pond=spec,
                )
                cap_src = min_cap if fam == "pond_robust" else fv.cap[nominal]
                for w in fill_from:
                    t.fills_m3[w] = cap_src[w] - t.receipts_direct_mm.get(w, 0.0) * area * 10
                    if fam == "pond_shift" and w in t.receipts_direct_mm:
                        t.fills_m3[w] = cap_src[w]  # store the whole early turn
                        t.receipts_direct_mm.pop(w)
                for dp in rel:
                    t.releases_mm.append((ctx.planting + timedelta(days=dp), RELEASE_DEPTH_MM))
                out.append(t)
    return out


def _b0_pond(ctx: SeasonContext, fv: FieldView, t: Template, spec: PondSpec, sid: str) -> None:
    """B0 pond habit: store pre-plant turns; release 60 mm after 21 days without water."""
    t.pond = spec
    for w in fv.windows:
        if fv.dap[w] < 0:
            t.fills_m3[w] = fv.cap[sid][w]
    wet_days = sorted(fv.end_date[w] for w in t.receipts_direct_mm)
    last = ctx.planting
    stop = ctx.planting + timedelta(days=B0_STOP_DAP[ctx.season.crop])
    d = ctx.planting
    while d <= stop:
        if d in wet_days:
            last = d
        elif (d - last).days >= B0_POND_DRY_DAYS:
            t.releases_mm.append((d, RELEASE_DEPTH_MM))
            last = d
        d += timedelta(days=1)


# --------------------------------------------------------------------------- template -> policy


def _receipt_event(ctx: SeasonContext, fid: str, wid: str, vol: float) -> LedgerEvent:
    w = ctx.windows[wid]
    return LedgerEvent(
        event_id=f"rcpt:{fid}:{wid}",
        timestamp=to_utc(w.end),
        explicit_order=0,
        kind=LedgerEventKind.outlet_receipt,
        volume_m3=vol,
        field_id=fid,
        window_id=wid,
    )


def finalize_pond(ctx: SeasonContext, t: Template) -> None:
    """Size controlled fills/releases so capacity and inventory hold in every weather state."""
    if t.pond is None:
        return
    spec = t.pond
    area10 = t.area_ha * 10.0
    planned: list[tuple[datetime, int, str, str, float]] = []
    for wid, v in t.fills_m3.items():
        if v > 0:
            planned.append((to_utc(ctx.windows[wid].end), 1, "fill", wid, v))
    for d, mm in t.releases_mm:
        planned.append((at_local(d, 6), 0, "release", d.isoformat(), mm * area10))
    planned.sort()
    done: list[LedgerEvent] = []
    fills: dict[str, float] = {}
    releases: list[tuple[date, float]] = []
    states = list(ctx.weather_daily.values())
    for ts, order, kind, ref, vol in planned:
        if spec.commissioned_on and local_crop_date(ts) < spec.commissioned_on:
            continue
        invs = []
        for wd in states:
            _, trace = exogenous_events(
                spec,
                done,
                wd,
                [d for d in ctx.days if day_end(d) <= ts] or [],
                active_from=spec.commissioned_on,
            )
            invs.append(trace.terminal_m3 if trace.events else spec.initial_inventory_m3)
        if kind == "fill":
            v = min(vol, spec.usable_capacity_m3 - max(invs) - 1e-6)
            if spec.max_fill_m3_day is not None:
                v = min(v, spec.max_fill_m3_day)
            v = floor_volume(v)
            if v <= 0:
                continue
            fills[ref] = v
            done.append(
                LedgerEvent(
                    event_id=f"fill:{spec.asset_id}:{ref}",
                    timestamp=ts,
                    explicit_order=1,
                    kind=LedgerEventKind.pond_fill,
                    volume_m3=v,
                    asset_id=spec.asset_id,
                    field_id=t.field_id,
                    window_id=ref,
                )
            )
        else:
            v = min(vol, min(invs) - 1e-6)
            if spec.max_release_m3_day is not None:
                v = min(v, spec.max_release_m3_day)
            mm = floor_grid(v / area10)
            if mm <= 0:
                continue
            releases.append((date.fromisoformat(ref), mm))
            done.append(
                LedgerEvent(
                    event_id=f"rel:{spec.asset_id}:{ref}",
                    timestamp=ts,
                    explicit_order=0,
                    kind=LedgerEventKind.pond_release,
                    volume_m3=mm * area10,
                    asset_id=spec.asset_id,
                    field_id=t.field_id,
                )
            )
    t.fills_m3 = fills
    t.releases_mm = releases


def floor_volume(v: float) -> float:
    return max(0.0, int(v * 1000) / 1000.0)


def day_end(d: date) -> datetime:
    return to_utc(datetime(d.year, d.month, d.day, tzinfo=PKT) + timedelta(days=1))


def schedule_of(ctx: SeasonContext, t: Template) -> dict[date, float]:
    s: dict[date, float] = defaultdict(float)
    for wid, mm in t.receipts_direct_mm.items():
        s[local_crop_date(ctx.windows[wid].end)] += mm
    for d, mm in t.releases_mm:
        s[d] += mm
    for d, mm in t.pumps_mm:
        s[d] += mm
    return {d: v for d, v in sorted(s.items()) if v > 0}


def enforce_daily_limit(ctx: SeasonContext, t: Template) -> None:
    """Trim pump/release/direct depths so no day exceeds the field application limit."""
    limit = ctx.crop.max_daily_irrigation_mm
    for _ in range(3):
        sched = schedule_of(ctx, t)
        over = {d: v - limit for d, v in sched.items() if v > limit + 1e-9}
        if not over:
            return
        for d, ex in over.items():
            for lst in (t.pumps_mm, t.releases_mm):
                for i, (dd, mm) in enumerate(lst):
                    if dd == d and ex > 0:
                        cut = min(mm, ex)
                        lst[i] = (dd, floor_grid(mm - cut))
                        ex -= cut
            for wid in list(t.receipts_direct_mm):
                if local_crop_date(ctx.windows[wid].end) == d and ex > 0:
                    mm = t.receipts_direct_mm[wid]
                    cut = min(mm, ex)
                    t.receipts_direct_mm[wid] = floor_grid(mm - cut - 1e-9)
                    ex -= cut
        t.pumps_mm = [(d, m) for d, m in t.pumps_mm if m > 0]
        t.releases_mm = [(d, m) for d, m in t.releases_mm if m > 0]
        t.receipts_direct_mm = {w: m for w, m in t.receipts_direct_mm.items() if m > 0}


def truncate(ctx: SeasonContext, t: Template, last_day: date) -> Template:
    """Drop field water after ``last_day`` (crop terminated): those turns are not taken."""
    t2 = Template(
        **{
            **t.__dict__,
            "receipts_direct_mm": dict(t.receipts_direct_mm),
            "fills_m3": dict(t.fills_m3),
            "releases_mm": list(t.releases_mm),
            "pumps_mm": list(t.pumps_mm),
            "tags": list(t.tags),
            "instances": list(t.instances),
            "params": dict(t.params),
        }
    )
    t2.receipts_direct_mm = {
        w: m
        for w, m in t2.receipts_direct_mm.items()
        if local_crop_date(ctx.windows[w].end) <= last_day
    }
    t2.releases_mm = [(d, m) for d, m in t2.releases_mm if d <= last_day]
    t2.pumps_mm = [(d, m) for d, m in t2.pumps_mm if d <= last_day]
    t2.truncated_after = last_day
    if "truncated" not in t2.tags:
        t2.tags.append("truncated")
    return t2


def experiments_for(ctx: SeasonContext, t: Template, soil_id: str) -> dict[str, CropExperiment]:
    sched = schedule_of(ctx, t)
    return {
        wid: make_experiment(
            ctx.crop.crop_profile_id,
            soil_id,
            wid,
            ws.transformed_sha256,
            ctx.season.sim_start,
            ctx.season.sim_end,
            t.app_eff,
            sorted(sched.items()),
        )
        for wid, ws in ctx.weather.items()
    }


def build_policy(
    ctx: SeasonContext,
    t: Template,
    outcomes_by_weather: dict[str, tuple[str, float]],
    pilot_hash: str,
) -> CandidatePolicy:
    area10 = t.area_ha * 10.0
    receipts = []
    for wid in sorted(
        set(t.receipts_direct_mm) | set(t.fills_m3), key=lambda w: to_utc(ctx.windows[w].end)
    ):
        vol = t.receipts_direct_mm.get(wid, 0.0) * area10 + t.fills_m3.get(wid, 0.0)
        if vol > 0:
            receipts.append(_receipt_event(ctx, t.field_id, wid, vol))
    pond_events = []
    if t.pond:
        for wid, v in t.fills_m3.items():
            pond_events.append(
                LedgerEvent(
                    event_id=f"fill:{t.pond.asset_id}:{wid}",
                    timestamp=to_utc(ctx.windows[wid].end),
                    explicit_order=1,
                    kind=LedgerEventKind.pond_fill,
                    volume_m3=v,
                    asset_id=t.pond.asset_id,
                    field_id=t.field_id,
                    window_id=wid,
                )
            )
        for d, mm in t.releases_mm:
            pond_events.append(
                LedgerEvent(
                    event_id=f"rel:{t.pond.asset_id}:{d.isoformat()}",
                    timestamp=at_local(d, 6),
                    explicit_order=0,
                    kind=LedgerEventKind.pond_release,
                    volume_m3=mm * area10,
                    asset_id=t.pond.asset_id,
                    field_id=t.field_id,
                )
            )
    pump_events = [
        LedgerEvent(
            event_id=f"pump:{t.pump_id}:{t.field_id}:{d.isoformat()}",
            timestamp=at_local(d, 7),
            explicit_order=0,
            kind=LedgerEventKind.pump_abstraction,
            volume_m3=mm * area10,
            asset_id=t.pump_id,
            field_id=t.field_id,
        )
        for d, mm in t.pumps_mm
    ]
    sched = schedule_of(ctx, t)
    pump_vol = sum(e.volume_m3 for e in pump_events)
    opex = ctx.pumps[t.pump_id].cost_pkr(pump_vol) if t.pump_id and pump_vol > 0 else 0
    new_pond = bool(t.pond and t.pond.asset_id in ctx.pond_instance)
    uses = ([t.pond.asset_id] if t.pond and (pond_events or new_pond) else []) + (
        [t.pump_id] if pump_events else []
    )
    nominal_caps = (
        {
            w.window_id: ctx.cap(
                w.window_id, ctx.resolved[scenarios.NOMINAL], t.config_id
            ).field_cap_m3
            for w in ctx.windows_by_field.get(t.field_id, [])
        }
        if scenarios.NOMINAL in ctx.resolved
        else {}
    )
    take_frac = max(
        (
            e.volume_m3 / nominal_caps[e.window_id]
            for e in receipts
            if nominal_caps.get(e.window_id)
        ),
        default=0.0,
    )
    body = {
        "field": t.field_id,
        "config": t.config_id,
        "family": t.family,
        "eff": t.app_eff,
        "area": t.area_ha,
        "receipts": [e.model_dump(mode="json") for e in receipts],
        "pond": [e.model_dump(mode="json") for e in pond_events],
        "pump": [e.model_dump(mode="json") for e in pump_events],
        "schedule": [[d.isoformat(), v] for d, v in sched.items()],
        "instances": sorted(t.instances),
        "uses": sorted(uses),
        "experiments": sorted(h for h, _ in outcomes_by_weather.values()),
        "pilot": pilot_hash,
        "roster": ctx.pilot.roster_hash(ctx.season.season_id),
        "generator": GENERATOR_VERSION,
    }
    h = content_hash(body)
    pol = CandidatePolicy(
        candidate_policy_id=f"cp_{h[:24]}",
        candidate_policy_hash=h,
        field_id=t.field_id,
        crop_profile_id=ctx.crop.crop_profile_id,
        soil_profile_id=ctx.pilot.fields[t.field_id].soil_profile_id,
        shared_configuration_id=t.config_id,
        required_instance_ids=sorted(set(t.instances)),
        family=t.family,
        coverage_tags=sorted(set(t.tags)),
        receipt_events=receipts,
        application_schedule=[IrrigationEvent(date=d, gross_depth_mm=v) for d, v in sched.items()],
        pond_events=pond_events,
        pump_events=pump_events,
        application_efficiency=t.app_eff,
        cropped_area_ha=t.area_ha,
        seasonal_opex_pkr=opex,
        outcomes=[],
        generator_version=GENERATOR_VERSION,
        template_id=t.key()[:16],
        uses_asset_ids=sorted(uses),
        receipt_volume_m3=sum(e.volume_m3 for e in receipts),
        pump_volume_m3=pump_vol,
        gross_application_mm=sum(sched.values()),
        attributes={
            "max_window_take_fraction": round(take_frac, 9),
            "params": t.params,
            "truncated_after": t.truncated_after.isoformat() if t.truncated_after else None,
            "energy_kwh": (
                ctx.pumps[t.pump_id].energy_kwh(pump_vol) if t.pump_id and pump_vol else None
            ),
        },
    )
    # per-state outcomes
    outs: list[StateOutcome] = []
    base_routed = None
    for wid in ctx.weather:
        for sid, rs in ctx.resolved.items():
            ev = evaluate_events(pol, ctx, rs, wid, t.config_id)
            exp_hash, yld = outcomes_by_weather.get(wid, (None, None))
            ok = ev.residuals.ok and yld is not None
            routed_uses = resource_uses(ev.routed)
            if sid == scenarios.NOMINAL and base_routed is None:
                base_routed = routed_uses
            outs.append(
                StateOutcome(
                    state_id=scenarios.state_id(wid, sid),
                    deliverable=ok,
                    crop_outcome_hash=exp_hash if ok else None,
                    yield_kg_ha=yld if ok else None,
                    production_kg=units.production_kg(t.area_ha, yld) if ok else None,
                    resources=routed_uses if ok else [],
                    service_credit_m3=ev.canal_receipt_m3 if ok else 0.0,
                    groundwater_m3=ev.groundwater_m3 if ok else 0.0,
                    canal_receipt_m3=ev.canal_receipt_m3,
                    weather_scenario_id=wid,
                    supply_profile_id=sid,
                    violations=[]
                    if ok
                    else (ev.residuals.reasons()[:8] or ["no exact crop outcome"]),
                    pond_loss_m3=ev.pond_loss_m3,
                    pond_spill_m3=ev.pond_spill_m3,
                    pond_rain_m3=ev.pond_rain_m3,
                    terminal_pond_m3=ev.terminal_pond_m3,
                )
            )
    base_routed = base_routed or []
    base_key = [(u.resource_id, u.interval_id, u.volume_m3) for u in base_routed]
    for o in outs:  # store state resources only when they differ from the invariant use
        if (
            o.deliverable
            and [(u.resource_id, u.interval_id, u.volume_m3) for u in o.resources] == base_key
        ):
            o.resources = []
    pol.outcomes = outs
    pol.resources = base_routed
    return pol


# --------------------------------------------------------------------------- dominance


def _res_map(p: CandidatePolicy, o: StateOutcome) -> dict[tuple[str, str], float]:
    src = o.resources or p.resources
    return {(u.resource_id, u.interval_id): u.volume_m3 for u in src}


def dominates(a: CandidatePolicy, b: CandidatePolicy) -> bool:
    """Safe dominance (T5.6): a at least as good as b on every criterion, all states."""
    if a.candidate_policy_id == b.candidate_policy_id:
        return False
    if not set(a.required_instance_ids) <= set(b.required_instance_ids):
        return False
    if not set(a.uses_asset_ids) <= set(b.uses_asset_ids):
        return False
    if a.seasonal_opex_pkr > b.seasonal_opex_pkr or a.pump_volume_m3 > b.pump_volume_m3 + 1e-9:
        return False
    ao = {o.state_id: o for o in a.outcomes}
    for ob in b.outcomes:
        oa = ao.get(ob.state_id)
        if oa is None:
            return False
        if ob.deliverable and not oa.deliverable:
            return False
        if not ob.deliverable:
            continue
        if (oa.production_kg or 0) < (ob.production_kg or 0) - 1e-9:
            return False
        if oa.service_credit_m3 < ob.service_credit_m3 - 1e-9:
            return False
        if oa.terminal_pond_m3 < ob.terminal_pond_m3 - 1e-9:
            return False
        ra, rb = _res_map(a, oa), _res_map(b, ob)
        for k, v in ra.items():
            if v > rb.get(k, 0.0) + 1e-9:
                return False
    return True


def prune(
    policies: list[CandidatePolicy], keep_families: Iterable[str] = ("rainfed", "baseline_B0")
) -> tuple[list[CandidatePolicy], int]:
    keep = set(keep_families)
    retained: list[CandidatePolicy] = []
    removed = 0
    for p in policies:
        if p.family in keep:
            retained.append(p)
            continue
        if any(
            dominates(q, p)
            for q in policies
            if q is not p
            and not (dominates(p, q) and q.candidate_policy_hash > p.candidate_policy_hash)
        ):
            removed += 1
            continue
        retained.append(p)
    return retained, removed


# --------------------------------------------------------------------------- build


@dataclass
class BuildResult:
    library: CandidateLibrary
    policies: list[CandidatePolicy]
    stats: dict[str, Any]


def build_from_context(
    ctx: SeasonContext,
    *,
    workers: int | None = None,
    progress: bool = False,
    extra_templates=None,
    field_ids: list[str] | None = None,
) -> BuildResult:
    t0 = time.perf_counter()
    pilot_hash = ctx.pilot.fields_hash()
    fids = field_ids or sorted(ctx.pilot.fields)
    templates: list[Template] = []
    gen_count: dict[tuple[str, str], int] = defaultdict(int)
    rejected: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cid in ctx.configs:
        for fid in fids:
            fv = field_view(ctx, fid, cid)
            ts = make_templates(ctx, fv, cid)
            if extra_templates:
                ts += list(extra_templates(ctx, fv, cid))
            gen_count[(fid, cid)] += len(ts)
            for t in ts:
                enforce_daily_limit(ctx, t)
                finalize_pond(ctx, t)
                enforce_daily_limit(ctx, t)
                if (
                    t.pond is not None
                    and not t.fills_m3
                    and not t.releases_mm
                    and t.family != "baseline_B0"
                ):
                    rejected[(fid, cid)]["pond_unused_after_sizing"] += 1
                    continue
                if t.pond is not None and not t.fills_m3 and not t.releases_mm:
                    t.pond = None  # B0 habit found no pond use this season
                templates.append(t)
    # exact experiments with truncation rounds (crop termination before late turns)
    soil_of = {fid: ctx.pilot.fields[fid].soil_profile_id for fid in fids}
    pending = templates
    final: list[tuple[Template, dict[str, tuple[str, float]]]] = []
    n_exp = 0
    exec_total = cached_total = 0
    for rnd in range(MAX_TRUNCATION_ROUNDS + 1):
        exps: dict[str, CropExperiment] = {}
        plan: list[tuple[Template, dict[str, str]]] = []
        for t in pending:
            e = experiments_for(ctx, t, soil_of[t.field_id])
            hs = {}
            for wid, exp in e.items():
                h = crop_experiment_hash(exp)
                exps[h] = exp
                hs[wid] = h
            plan.append((t, hs))
        rep = run_batch(exps.values(), workers=workers, progress=progress)
        n_exp += len(exps)
        exec_total += rep.executed
        cached_total += rep.cached
        nxt: list[Template] = []
        for t, hs in plan:
            errs = {w: rep.failed.get(h) for w, h in hs.items() if h in rep.failed}
            if not errs:
                final.append((t, {w: (h, rep.outcomes[h].yield_kg_ha) for w, h in hs.items()}))
                continue
            terms = []
            for msg in errs.values():
                if msg and "after crop termination" in msg:
                    terms.append(date.fromisoformat(msg.rsplit("termination ", 1)[1][:10]))
                else:
                    terms = None
                    break
            if terms is not None and rnd < MAX_TRUNCATION_ROUNDS:
                nxt.append(truncate(ctx, t, min(terms) - timedelta(days=1)))
            else:
                reason = "crop_experiment_failed: " + (next(iter(errs.values())) or "")[:160]
                rejected[(t.field_id, t.config_id)][
                    reason.split(":")[0] + ":" + reason.split(":")[1][:40]
                ] += 1
        pending = nxt
        if not pending:
            break
    # policies
    by_fc: dict[tuple[str, str], list[CandidatePolicy]] = defaultdict(list)
    seen: set[str] = set()
    for t, outs in final:
        p = build_policy(ctx, t, outs, pilot_hash)
        if p.candidate_policy_hash in seen:
            rejected[(t.field_id, t.config_id)]["duplicate_of_existing_policy"] += 1
            continue
        seen.add(p.candidate_policy_hash)
        if t.family != "rainfed" and not any(o.deliverable for o in p.outcomes):
            rejected[(t.field_id, t.config_id)]["undeliverable_in_every_state"] += 1
            continue
        by_fc[(t.field_id, t.config_id)].append(p)
    policies: list[CandidatePolicy] = []
    coverage: list[LibraryCoverage] = []
    for (fid, cid), ps in sorted(by_fc.items()):
        kept, removed = prune(ps)
        if removed:
            rejected[(fid, cid)]["safely_dominated"] += removed
        if not any(p.family == "rainfed" for p in kept):
            raise CandidateError(f"{fid}/{cid}: mandatory zero-receipt policy missing")
        policies.extend(kept)
        fam: dict[str, int] = defaultdict(int)
        for p in kept:
            fam[p.family] += 1
        coverage.append(
            LibraryCoverage(
                field_id=fid if len(ctx.configs) == 1 else f"{fid}@{cid}",
                generated=gen_count[(fid, cid)],
                rejected=sum(rejected[(fid, cid)].values()),
                retained=len(kept),
                rejection_reasons=dict(rejected[(fid, cid)]),
                families=dict(fam),
            )
        )
    policies.sort(
        key=lambda p: (p.field_id, p.shared_configuration_id, p.family, p.candidate_policy_id)
    )
    state_ids = ctx.state_ids()
    lib_hash = content_hash(
        {
            "policies": [p.candidate_policy_hash for p in policies],
            "states": state_ids,
            "configs": sorted(ctx.configs),
            "pilot": pilot_hash,
            "pilot_version": ctx.pilot.pilot_version,
            "season": ctx.season.season_id,
            "weather": sorted(ws.transformed_sha256 for ws in ctx.weather.values()),
            "supply": sorted(rs.resolved_hash for rs in ctx.resolved.values()),
            "generator": GENERATOR_VERSION,
            "adapter": ADAPTER_VERSION,
        }
    )
    rel = f"{ctx.pilot.pilot_id}/{ctx.season.season_id}/{lib_hash}"
    per_field = defaultdict(int)
    for p in policies:
        per_field[(p.field_id, p.shared_configuration_id)] += 1
    stats = {
        "fields": len(fids),
        "configurations": len(ctx.configs),
        "templates": len(templates),
        "experiments_requested": n_exp,
        "experiments_executed": exec_total,
        "experiments_cached": cached_total,
        "policies_retained": len(policies),
        "options_per_field_min": min(per_field.values()) if per_field else 0,
        "options_per_field_max": max(per_field.values()) if per_field else 0,
        "wall_s": round(time.perf_counter() - t0, 2),
        "pilot_label": ctx.pilot.label,
        "decision_at": ctx.decision_at.isoformat(),
    }
    lib = CandidateLibrary(
        candidate_library_hash=lib_hash,
        pilot_id=ctx.pilot.pilot_id,
        pilot_version=ctx.pilot.pilot_version,
        season_id=ctx.season.season_id,
        state_ids=state_ids,
        configurations=list(ctx.configs.values()),
        policies_ref=f"{rel}/policies.jsonl",
        coverage=coverage,
        generator_version=GENERATOR_VERSION,
        created_at=datetime.now(UTC),
        intervals=ctx.intervals,
        capacities=library_capacities(ctx),
        typical_state_id=ctx.typical_state_id(),
        supply_profile_ids=list(ctx.supply_profiles),
        weather_scenario_ids=list(ctx.weather),
        decision_at=ctx.decision_at,
        excluded_instances=ctx.excluded_instances,
        build_stats=stats,
    )
    return BuildResult(lib, policies, stats)


def publish_library(res: BuildResult) -> CandidateLibrary:
    """Publish once per content hash; a rebuild may restore ignored policy dumps.

    Runtime build statistics belong to the current build result, while the
    original publication metadata remains frozen on disk (PRD §8.6, T3.6).
    """
    lib = res.library
    d = libraries_dir() / lib.pilot_id / lib.season_id / lib.candidate_library_hash
    d.mkdir(parents=True, exist_ok=True)
    metadata_path = d / "library.json"
    policies_path = d / "policies.jsonl"
    if metadata_path.exists():
        original = CandidateLibrary.model_validate_json(metadata_path.read_text())
        runtime_fields = {"created_at", "build_stats"}
        if original.model_dump(exclude=runtime_fields) != lib.model_dump(exclude=runtime_fields):
            raise CandidateError(
                "refusing to replace immutable library metadata under the same hash"
            )
        lib = lib.model_copy(update={"created_at": original.created_at})
    if policies_path.exists():
        with policies_path.open() as fh:
            original_policies = [
                CandidatePolicy.model_validate_json(line) for line in fh if line.strip()
            ]
        if original_policies != res.policies:
            raise CandidateError("refusing to replace immutable policies under the same hash")
    else:
        tmp = d / ".policies.jsonl.tmp"
        with tmp.open("w") as fh:
            for p in res.policies:
                fh.write(p.model_dump_json(exclude_defaults=True) + "\n")
        tmp.replace(policies_path)
    if not metadata_path.exists():
        atomic_write_text(metadata_path, lib.model_dump_json(indent=1))
    atomic_write_text(
        libraries_dir() / lib.pilot_id / lib.season_id / "latest.json",
        json.dumps(
            {
                "candidate_library_hash": lib.candidate_library_hash,
                "created_at": lib.created_at.isoformat(),
                "pilot_version": lib.pilot_version,
                "policies": len(res.policies),
            },
            indent=1,
        ),
    )
    return lib


def build_library(
    pilot_id: str,
    season_id: str,
    *,
    extra_templates=None,
    workers: int | None = None,
    progress: bool = False,
    pilot_version: str | None = None,
) -> CandidateLibrary:
    """Generate, validate and publish an immutable candidate library (STREAMS.md entry point)."""
    ctx = build_season_context(load_pilot(pilot_id, pilot_version), season_id)
    return publish_library(
        build_from_context(ctx, workers=workers, progress=progress, extra_templates=extra_templates)
    )


def load_library(
    pilot_id: str, season_id: str, library_hash: str | None = None
) -> tuple[CandidateLibrary, list[CandidatePolicy]]:
    base = libraries_dir() / pilot_id / season_id
    if library_hash is None:
        latest = base / "latest.json"
        if not latest.exists():
            raise FileNotFoundError(f"no candidate library published for {pilot_id}/{season_id}")
        library_hash = json.loads(latest.read_text())["candidate_library_hash"]
    d = base / library_hash
    lib = CandidateLibrary.model_validate_json((d / "library.json").read_text())
    if lib.candidate_library_hash != library_hash:
        raise CandidateError("library.json hash does not match its directory")
    pols = []
    with (d / "policies.jsonl").open() as fh:
        for line in fh:
            if line.strip():
                pols.append(CandidatePolicy.model_validate_json(line))
    return lib, pols
