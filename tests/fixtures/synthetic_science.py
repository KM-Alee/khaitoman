"""TEST FIXTURE: synthetic candidate library + science bindings for API/optimizer tests.

Labelled synthetic data only. Yields come from a closed-form toy response, not
from AquaCrop; ledgers are a simplified routing of each policy's receipts. The
real science stream entry points are exercised by the scientific integration test
instead. Selected by ``Settings.science_bindings`` in tests only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import (
    AtomicInterval,
    CandidateLibrary,
    CandidatePolicy,
    IrrigationEvent,
    LedgerEvent,
    LedgerEventKind,
    LibraryCoverage,
    PhysicalValidationReport,
    ResourceCapacity,
    ResourceUse,
    RuleResidual,
    SharedConfiguration,
    StateOutcome,
)
from tests.fixtures import synthetic as fx

LABEL = "TEST FIXTURE synthetic library"
WINDOW_M3 = 0.03 * 6 * 3600  # 648 m3 at the outlet boundary per turn
PATH = {"head": 0.95 * 0.9, "tail": 0.95 * 0.65, "tail_repaired": 0.95 * 0.9}
SUPPLY_MULT = {"nominal-roster-v1": 1.0, "shortage-22pct-v1": 0.78, "interruption-14d-v1": 1.0}
CLOSED_TURNS = {"interruption-14d-v1": {1}}
RAINFED = {"dry": 1500.0, "typical": 2200.0, "wet": 2600.0}
FULL = {"dry": 4200.0, "typical": 5000.0, "wet": 5200.0}
CFG_BASE = "cfg:base"
CFG_REP = f"cfg:{fx.REPAIR}"
PUMP = "fixture-a:pump-shared"
POND = "fixture-a:pond-existing"
PUMP_M3 = 900.0
PUMP_RATE = "12.5"


def turn_start(field_index: int, turn: int) -> datetime:
    return datetime(2026, 12, 1, tzinfo=UTC) + timedelta(days=21 * turn, hours=6 * field_index)


@dataclass
class Tpl:
    family: str
    takes: tuple[float, float, float]
    instances: tuple[str, ...] = ()
    gain: float = 1.0
    pump_m3: float = 0.0
    area_loss_m2: float = 0.0
    uses: tuple[str, ...] = ()
    invalid: bool = False


def templates(fid: str) -> list[Tpl]:
    out = [
        Tpl("rainfed", (0, 0, 0)),
        Tpl("baseline_B0", (1, 1, 1)),
        Tpl("baseline_B0", (0.78, 0.78, 0.78)),
        Tpl("baseline_B0", (1, 0, 1)),
        Tpl("full_window", (1, 1, 1)),
        Tpl("deficit", (0.78, 0.78, 0.78)),
        Tpl("skip_mid", (1, 0, 1)),
        Tpl("robust_low", (0.78, 0, 0.78)),
    ]
    if fid == "fixture-a:f1":
        out += [
            Tpl("leveled", (1, 1, 1), (fx.LEVEL,), gain=1.25),
            Tpl("leveled", (0.78, 0, 0.78), (fx.LEVEL,), 1.25),
        ]
    if fid == "fixture-a:f2":
        out += [
            Tpl("pond_shift", (1, 1, 1), gain=1.10, uses=(POND,)),
            Tpl("pond_shift", (0.78, 0, 0.78), gain=1.1, uses=(POND,)),
        ]
    if fid in ("fixture-a:f3", "fixture-a:f4"):
        out += [
            Tpl("pump_topup", (1, 1, 1), pump_m3=PUMP_M3, uses=(PUMP,)),
            Tpl("pump_topup", (0.78, 0, 0.78), pump_m3=PUMP_M3, uses=(PUMP,)),
        ]
    if fid == "fixture-a:f3":
        out += [
            Tpl("pond_new", (1, 1, 1), (fx.POND_S,), gain=1.12, area_loss_m2=500),
            Tpl("pond_new", (1, 1, 1), (fx.POND_L,), gain=1.18, area_loss_m2=900),
        ]
    return out


def field_index(fid: str) -> int:
    return fx.FIELDS.index(fid)


def path_factor(fid: str, cfg: str) -> float:
    if fx.GROUPS[fid] in ("head", "middle"):
        return PATH["head"]
    return PATH["tail_repaired"] if cfg == CFG_REP else PATH["tail"]


def yield_for(weather: str, water_index: float, gain: float) -> float:
    w = max(0.0, min(1.0, water_index))
    return round(RAINFED[weather] + (FULL[weather] - RAINFED[weather]) * (w**0.7) * gain, 3)


def _policy(fid: str, cfg: str, t: Tpl, k: int) -> CandidatePolicy:
    i = field_index(fid)
    pf = path_factor(fid, cfg)
    area = fx.AREAS_HA[fid] - t.area_loss_m2 / 10000
    receipts = []
    resources = []
    sched = []
    total_receipt = 0.0
    for turn, take in enumerate(t.takes):
        if take <= 0:
            continue
        ts = turn_start(i, turn)
        at_field = WINDOW_M3 * take * pf
        total_receipt += at_field
        receipts.append(
            LedgerEvent(
                event_id=f"rcpt:{fid}:{turn}",
                timestamp=ts + timedelta(hours=6),
                kind="outlet_receipt",
                volume_m3=at_field,
                field_id=fid,
                window_id=f"{fid}:w{turn}",
            )
        )
        resources.append(
            ResourceUse(resource_id="source:src", interval_id=f"t{turn}", volume_m3=at_field / pf)
        )
        resources.append(
            ResourceUse(
                resource_id=f"edge:{'e-tail' if fx.GROUPS[fid] == 'tail' else 'e-head'}",
                interval_id=f"t{turn}",
                volume_m3=at_field / (pf / 0.95),
            )
        )
        sched.append(
            IrrigationEvent(
                date=(ts + timedelta(hours=11)).date(),
                gross_depth_mm=round(at_field / (area * 10), 6),
            )
        )
    pump_events = []
    if t.pump_m3:
        resources.append(
            ResourceUse(resource_id=f"gw:{PUMP}", interval_id="season", volume_m3=t.pump_m3)
        )
        pd_ = datetime(2027, 2, 10, 4, tzinfo=UTC)
        pump_events.append(
            LedgerEvent(
                event_id=f"pump:{fid}",
                timestamp=pd_,
                kind="pump_abstraction",
                volume_m3=t.pump_m3,
                field_id=fid,
                asset_id=PUMP,
            )
        )
        sched.append(
            IrrigationEvent(date=pd_.date(), gross_depth_mm=round(t.pump_m3 / (area * 10), 6))
        )
    ref = 3 * WINDOW_M3 * PATH["head"]
    water_index = (total_receipt + t.pump_m3) / ref
    outcomes = []
    for w in fx.WEATHER:
        for s in fx.SUPPLY:
            sid = fx.state_id(w, s)
            ok = all(take <= SUPPLY_MULT[s] + 1e-12 for take in t.takes)
            ok &= not any(t.takes[j] > 0 for j in CLOSED_TURNS.get(s, set()))
            y = yield_for(w, water_index, t.gain) if ok else None
            outcomes.append(
                StateOutcome(
                    state_id=sid,
                    deliverable=ok,
                    crop_outcome_hash=content_hash([LABEL, fid, t.family, k, w]) if ok else None,
                    yield_kg_ha=y,
                    production_kg=y * area if ok else None,
                    service_credit_m3=total_receipt if ok else 0.0,
                    canal_receipt_m3=total_receipt,
                    groundwater_m3=t.pump_m3,
                    weather_scenario_id=w,
                    supply_profile_id=s,
                    violations=[]
                    if ok
                    else ["synthetic: supply cannot deliver this receipt schedule"],
                    terminal_pond_m3=40.0 if t.family == "pond_shift" else 0.0,
                )
            )
    pid = f"{fid}:{cfg}:{t.family}:{k}"
    return CandidatePolicy(
        candidate_policy_id=pid,
        candidate_policy_hash=content_hash([LABEL, pid]),
        field_id=fid,
        crop_profile_id="fixture-wheat",
        soil_profile_id="fixture-loam",
        shared_configuration_id=cfg,
        required_instance_ids=list(t.instances),
        family=t.family,
        coverage_tags=[t.family, LABEL],
        receipt_events=receipts,
        application_schedule=sched,
        pump_events=pump_events,
        application_efficiency=0.75 if t.family == "leveled" else 0.6,
        cropped_area_ha=area,
        seasonal_opex_pkr=int(t.pump_m3 * float(PUMP_RATE)),
        outcomes=outcomes,
        generator_version=LABEL,
        resources=resources,
        uses_asset_ids=list(t.uses),
        receipt_volume_m3=total_receipt,
        pump_volume_m3=t.pump_m3,
        gross_application_mm=sum(e.gross_depth_mm for e in sched),
        attributes={"max_window_take_fraction": max(t.takes), "fixture_invalid": t.invalid},
    )


def build_library(
    data_dir: Path,
    *,
    invalid_family: str | None = None,
    gw_cap: float = 1500.0,
    source_cap: float | None = None,
) -> str:
    pols = []
    for cfg in (CFG_BASE, CFG_REP):
        for fid in fx.FIELDS:
            for k, t in enumerate(templates(fid)):
                if invalid_family and t.family == invalid_family:
                    t.invalid = True
                if cfg == CFG_REP and t.instances:
                    pass
                pols.append(_policy(fid, cfg, t, k))
    caps = [ResourceCapacity(resource_id=f"gw:{PUMP}", interval_id="season", capacity_m3=gw_cap)]
    if source_cap is not None:
        for turn in range(3):
            caps.append(
                ResourceCapacity(
                    resource_id="source:src", interval_id=f"t{turn}", capacity_m3=source_cap
                )
            )
    configs = [
        SharedConfiguration(
            shared_configuration_id=CFG_BASE,
            repair_instance_ids=[],
            capex_pkr=0,
            edge_delivery_factors={},
        ),
        SharedConfiguration(
            shared_configuration_id=CFG_REP,
            repair_instance_ids=[fx.REPAIR],
            capex_pkr=200000,
            edge_delivery_factors={"e-tail": 0.9},
        ),
    ]
    cov = []
    for fid in fx.FIELDS:
        n = sum(1 for p in pols if p.field_id == fid)
        cov.append(LibraryCoverage(field_id=fid, generated=n, rejected=0, retained=n))
    h = content_hash(
        [LABEL, [p.candidate_policy_hash for p in pols], gw_cap, source_cap, invalid_family]
    )
    lib = CandidateLibrary(
        candidate_library_hash=h,
        pilot_id=fx.PILOT_ID,
        pilot_version=fx.VERSION,
        season_id=fx.SEASON_ID,
        state_ids=[fx.state_id(w, s) for w in fx.WEATHER for s in fx.SUPPLY],
        configurations=configs,
        policies_ref=f"{fx.PILOT_ID}/{fx.SEASON_ID}/{h}/policies.jsonl",
        coverage=cov,
        generator_version=LABEL,
        created_at=datetime(2026, 10, 10, tzinfo=UTC),
        intervals=[
            AtomicInterval(
                interval_id=f"t{t}",
                start=turn_start(0, t),
                end=turn_start(3, t) + timedelta(hours=6),
            )
            for t in range(3)
        ],
        capacities=caps,
        typical_state_id=fx.state_id("typical", "nominal-roster-v1"),
        supply_profile_ids=fx.SUPPLY,
        weather_scenario_ids=fx.WEATHER,
        decision_at=fx.DECISION,
        excluded_instances={"fixture-a:f4:pond-late": "commissioned after planting"},
    )
    d = Path(data_dir) / "libraries" / fx.PILOT_ID / fx.SEASON_ID / h
    d.mkdir(parents=True, exist_ok=True)
    (d / "library.json").write_text(lib.model_dump_json(indent=1))
    with (d / "policies.jsonl").open("w") as fh:
        for p in pols:
            fh.write(p.model_dump_json() + "\n")
    (d.parent / "latest.json").write_text(
        json.dumps({"candidate_library_hash": h, "pilot_version": fx.VERSION})
    )
    return h


# ---------------------------------------------------------------------------- bindings


@dataclass(frozen=True)
class FxSupply:
    supply_profile_id: str
    multiplier: float
    closures: tuple
    resolved_hash: str


class FixtureScience:
    """Implements the ScienceBindings protocol over the synthetic library (tests only)."""

    def __init__(self, settings):
        self.root = Path(settings.data_dir) / "libraries"

    def load_library(self, pilot_id, season_id, library_hash=None):
        base = self.root / pilot_id / season_id
        if library_hash is None:
            library_hash = json.loads((base / "latest.json").read_text())["candidate_library_hash"]
        d = base / library_hash
        lib = CandidateLibrary.model_validate_json((d / "library.json").read_text())
        pols = [
            CandidatePolicy.model_validate_json(x)
            for x in (d / "policies.jsonl").read_text().splitlines()
            if x
        ]
        return lib, pols

    def resolve_supply(self, profile, extra_uniform_reduction=0.0):
        mult = 1.0
        closures = []
        for t in profile.transformations:
            if t.kind == "absolute_multiplier":
                mult = t.multiplier
            elif t.kind == "relative_multiplier":
                mult *= t.multiplier
            else:
                closures.append((t.start, t.end, frozenset(t.edge_ids), t.transformation_id))
        if extra_uniform_reduction:
            if profile.pre_reduced:
                raise ValueError("pre-reduced profile")
            mult *= 1 - extra_uniform_reduction
        return FxSupply(
            profile.supply_profile_id,
            mult,
            tuple(closures),
            content_hash([profile.supply_profile_id, mult]),
        )

    def closure(self, start, end, edge_ids, reason):
        return (start, end, frozenset(edge_ids), reason)

    def season_context(self, pilot_id, season_id, pilot_version):
        return {"pilot_id": pilot_id}

    def evaluate_policy(
        self,
        policy,
        ctx,
        resolved_supply,
        weather_scenario_id,
        config_id,
        *,
        state_id,
        extra_closures=(),
    ):
        base_sid = fx.state_id(weather_scenario_id, resolved_supply.supply_profile_id)
        base = next(o for o in policy.outcomes if o.state_id == base_sid)
        blocked = {e for c in extra_closures for e in c[2]}
        route = {"e-main", "e-tail" if fx.GROUPS[policy.field_id] == "tail" else "e-head"}
        frac = policy.attributes.get("max_window_take_fraction", 0)
        ok = base.deliverable and frac <= resolved_supply.multiplier + 1e-12
        if policy.receipt_volume_m3 > 0 and blocked & route:
            ok = False
        upd = {"state_id": state_id}
        if not ok:
            upd.update(
                deliverable=False,
                yield_kg_ha=None,
                production_kg=None,
                crop_outcome_hash=None,
                service_credit_m3=0.0,
                violations=["synthetic: blocked route or reduced supply"],
            )
        return base.model_copy(update=upd)

    def reconstruct(
        self,
        policy_ids,
        library,
        state_id,
        config_id,
        *,
        resolved_supply=None,
        extra_closures=(),
        policies=None,
    ):
        pols = policies or {
            p.candidate_policy_id: p
            for p in self.load_library(
                library.pilot_id, library.season_id, library.candidate_library_hash
            )[1]
        }
        events: list[LedgerEvent] = []
        res: list[RuleResidual] = []
        used: dict[tuple[str, str], float] = {}
        seen = set()
        for pid in policy_ids:
            p = pols[pid]
            if p.field_id in seen:
                res.append(
                    RuleResidual(rule="receipt_right", passed=False, entity_ids=[p.field_id])
                )
            seen.add(p.field_id)
            if p.attributes.get("fixture_invalid"):
                res.append(
                    RuleResidual(
                        rule="pond_capacity",
                        passed=False,
                        max_violation=12.5,
                        entity_ids=[pid],
                        detail="synthetic invalid policy (reconstruction failure fixture)",
                    )
                )
            pf = path_factor(p.field_id, config_id)
            for e in p.receipt_events:
                src = e.volume_m3 / pf
                events.append(
                    LedgerEvent(
                        event_id=f"src:{e.event_id}",
                        timestamp=e.timestamp,
                        explicit_order=-3,
                        kind=LedgerEventKind.source_release,
                        volume_m3=src,
                    )
                )
                events.append(
                    LedgerEvent(
                        event_id=f"loss:{e.event_id}",
                        timestamp=e.timestamp,
                        explicit_order=-1,
                        kind=LedgerEventKind.edge_loss,
                        volume_m3=src - e.volume_m3,
                        edge_id="e-tail" if fx.GROUPS[p.field_id] == "tail" else "e-head",
                    )
                )
                events.append(
                    LedgerEvent(
                        event_id=f"edge:{e.event_id}",
                        timestamp=e.timestamp,
                        explicit_order=-2,
                        kind=LedgerEventKind.edge_transfer,
                        volume_m3=src,
                        edge_id="e-tail" if fx.GROUPS[p.field_id] == "tail" else "e-head",
                    )
                )
                events.append(e)
                events.append(
                    e.model_copy(
                        update={
                            "event_id": f"app:{e.event_id}",
                            "kind": LedgerEventKind.field_application,
                            "explicit_order": 2,
                        }
                    )
                )
            for e in p.pump_events:
                events.append(e)
                events.append(
                    e.model_copy(
                        update={
                            "event_id": f"app:{e.event_id}",
                            "kind": LedgerEventKind.field_application,
                            "explicit_order": 2,
                        }
                    )
                )
            for r in p.resources:
                k = (r.resource_id, r.interval_id)
                used[k] = used.get(k, 0.0) + r.volume_m3
        for c in library.capacities:
            if c.state_id not in (None, state_id):
                continue
            u = used.get((c.resource_id, c.interval_id), 0.0)
            res.append(
                RuleResidual(
                    rule="shared_capacity",
                    passed=u <= c.capacity_m3 + 1e-6,
                    max_violation=max(0.0, u - c.capacity_m3),
                    entity_ids=[c.resource_id],
                )
            )
        status = "passed" if all(r.passed for r in res) else "failed"
        return sorted(
            events, key=lambda e: (e.timestamp, e.explicit_order, e.event_id)
        ), PhysicalValidationReport(status=status, residuals=res)

    def load_trajectory(self, crop_outcome_hash):
        days = [date(2026, 11, 15) + timedelta(days=i) for i in range(0, 150, 7)]
        return pd.DataFrame(
            {
                "date": days,
                "canopy_fraction": [min(0.95, i / 12) for i in range(len(days))],
                "biomass_kg_ha": [i * 300.0 for i in range(len(days))],
            }
        )

    def crop_outcome(self, crop_outcome_hash):
        return None


def bindings(settings) -> FixtureScience:
    return FixtureScience(settings)
