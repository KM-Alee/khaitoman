"""Frozen physical context for one pilot version and season.

Loads the pilot package contract (STREAMS.md) into domain objects, derives
commissioning dates (T4.6), admissible shared-repair configurations (T6.4),
atomic intervals (T4.1) and per-state window caps. The same context is used by
candidate generation and by ``ledger.reconstruct`` so both see identical inputs.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from aabflow.domain.calendar import PKT, local_crop_date, to_utc
from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.schemas import (
    ActionCategory,
    Asset,
    AssetKind,
    AtomicInterval,
    Edge,
    FieldRecord,
    InterventionInstance,
    InterventionType,
    Node,
    Pilot,
    RosterWindow,
    ServiceReference,
    SharedConfiguration,
    SoilProfile,
)
from aabflow.science.paths import pilots_dir
from aabflow.water.network import Network


class ContextError(ValueError):
    pass


def local_midnight_utc(d: date) -> datetime:
    return to_utc(datetime(d.year, d.month, d.day, tzinfo=PKT))


@dataclass
class PilotData:
    pilot_id: str
    pilot_version: str
    fields: dict[str, FieldRecord]
    network: Network
    nodes: list[Node]
    edges: list[Edge]
    roster: dict[str, list[RosterWindow]]
    assets: dict[str, Asset]
    types: dict[str, InterventionType]
    instances: dict[str, InterventionInstance]
    soils: dict[str, SoilProfile]
    service_refs: list[ServiceReference]
    pilot: Pilot | None = None
    package_dir: Path | None = None
    input_hashes: dict[str, str] = field(default_factory=dict)
    label: str = "pilot package"

    @property
    def is_test_fixture(self) -> bool:
        return self.label.startswith("TEST FIXTURE")

    def fields_hash(self) -> str:
        return content_hash(
            {
                "fields": [
                    f.model_dump(mode="json")
                    for f in sorted(self.fields.values(), key=lambda f: f.field_id)
                ],
                "nodes": [n.model_dump(mode="json") for n in self.nodes],
                "edges": [e.model_dump(mode="json") for e in self.edges],
                "assets": [
                    a.model_dump(mode="json")
                    for a in sorted(self.assets.values(), key=lambda a: a.asset_id)
                ],
                "instances": [
                    i.model_dump(mode="json")
                    for i in sorted(self.instances.values(), key=lambda i: i.instance_id)
                ],
            }
        )

    def roster_hash(self, season_id: str) -> str:
        return content_hash([w.model_dump(mode="json") for w in self.roster.get(season_id, [])])


def latest_version(pilot_id: str) -> str:
    idx = pilots_dir() / "index.json"
    if idx.exists():
        rows = json.loads(idx.read_text())
        rows = rows.get("pilots", rows) if isinstance(rows, dict) else rows
        vs = [r["pilot_version"] for r in rows if r.get("pilot_id") == pilot_id]
        if vs:
            return vs[-1]
    d = pilots_dir() / pilot_id
    vs = sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []
    if not vs:
        raise ContextError(f"no published version for {pilot_id}")
    return vs[-1]


def _read(path: Path) -> Any:
    if not path.exists():
        raise ContextError(f"pilot package file missing: {path}")
    return json.loads(path.read_text())


def load_pilot(pilot_id: str, pilot_version: str | None = None) -> PilotData:
    version = pilot_version or latest_version(pilot_id)
    d = pilots_dir() / pilot_id / version
    if not d.exists():
        raise ContextError(f"pilot package {d} not found")
    fc = _read(d / "fields.geojson")
    fields: dict[str, FieldRecord] = {}
    for feat in fc["features"]:
        props = {k: v for k, v in feat["properties"].items() if k in FieldRecord.model_fields}
        f = FieldRecord.model_validate(props)
        fields[f.field_id] = f
    net = _read(d / "network.json")
    nodes = [Node.model_validate(n) for n in net["nodes"]]
    edges = [Edge.model_validate(e) for e in net["edges"]]
    roster_raw = _read(d / "roster.json")
    roster = {
        sid: [RosterWindow.model_validate(w) for w in ws]
        for sid, ws in roster_raw.get("seasons", roster_raw).items()
    }
    assets = {a["asset_id"]: Asset.model_validate(a) for a in _read(d / "assets.json")}
    iv = _read(d / "interventions.json")
    types = {t["type_id"]: InterventionType.model_validate(t) for t in iv.get("types", [])}
    instances = {
        i["instance_id"]: InterventionInstance.model_validate(i) for i in iv.get("instances", [])
    }
    soils = {}
    if (d / "soils.json").exists():
        soils = {
            s["soil_profile_id"]: SoilProfile.model_validate(s) for s in _read(d / "soils.json")
        }
    refs = []
    if (d / "service_reference.json").exists():
        refs = [ServiceReference.model_validate(r) for r in _read(d / "service_reference.json")]
    pilot = Pilot.model_validate(_read(d / "pilot.json")) if (d / "pilot.json").exists() else None
    hashes = {
        p.name: file_sha256(p)
        for p in sorted(d.glob("*.json*"))
        if p.name
        in {
            "fields.geojson",
            "network.json",
            "roster.json",
            "assets.json",
            "interventions.json",
            "soils.json",
            "service_reference.json",
            "pilot.json",
        }
    }
    label = "pilot package"
    if (d / "FIXTURE_LABEL").exists():  # labelled synthetic test fixture, never pilot evidence
        label = "TEST FIXTURE: " + (d / "FIXTURE_LABEL").read_text().strip()
    return PilotData(
        pilot_id,
        version,
        fields,
        Network.from_records(nodes, edges),
        nodes,
        edges,
        roster,
        assets,
        types,
        instances,
        soils,
        refs,
        pilot,
        d,
        hashes,
        label,
    )


# --------------------------------------------------------------------------- commissioning


def commissioned_on(inst: InterventionInstance, decision_at: datetime) -> date:
    """decision date + procurement/start delay + construction/service lead time (T4.6)."""
    return local_crop_date(decision_at) + timedelta(
        days=inst.procurement_delay_days + inst.lead_time_days
    )


PROPOSED_COST_CATEGORIES = {
    ActionCategory.pond,
    ActionCategory.shared_repair,
    ActionCategory.leveling,
}


def missing_cost(inst: InterventionInstance) -> str | None:
    """Proposed works need a nonzero dated cost (or an explicit reviewed zero)."""
    if (
        inst.category in PROPOSED_COST_CATEGORIES
        and inst.capex_pkr <= 0
        and not inst.parameters.get("zero_cost_reviewed")
    ):
        return f"{inst.instance_id}: capex missing (0 PKR without a reviewed zero-cost record)"
    return None


def instance_admissibility(
    inst: InterventionInstance, decision_at: datetime, planting: date, pilot: PilotData
) -> str | None:
    """Reason the instance cannot be used this season, or None if admissible."""
    mc = missing_cost(inst)
    if mc:
        return mc
    for tid in inst.target_ids:
        if tid not in pilot.fields and tid not in pilot.network.edges and tid not in pilot.assets:
            return f"{inst.instance_id}: target {tid} not in pilot version {pilot.pilot_version}"
    for pre in inst.prerequisites:
        if pre not in pilot.instances and pre not in pilot.assets:
            return f"{inst.instance_id}: prerequisite {pre} not in pilot version"
    on = commissioned_on(inst, decision_at)
    timed = (ActionCategory.pond, ActionCategory.leveling, ActionCategory.shared_repair)
    if inst.category in timed and on > planting:
        return (
            f"{inst.instance_id}: commissioned {on} after planting {planting} "
            f"(decision {local_crop_date(decision_at)} + {inst.procurement_delay_days} + "
            f"{inst.lead_time_days} days); v2 requires commissioning before planting"
        )
    if inst.category is ActionCategory.pump_supplement:
        for tid in inst.target_ids:
            a = pilot.assets.get(tid)
            if a is None or a.kind is not AssetKind.pump or not a.existing:
                return f"{inst.instance_id}: pump supplementation needs an existing pump asset"
    return None


def asset_available_on(a: Asset) -> date | None:
    if a.existing and a.commissioned_at is None:
        raise ContextError(f"existing asset {a.asset_id} lacks an explicit commissioned_at date")
    return a.commissioned_at


# --------------------------------------------------------------------------- configurations


def configurations(
    pilot: PilotData, decision_at: datetime, planting: date
) -> tuple[
    list[SharedConfiguration], dict[str, list[tuple[str, datetime, datetime]]], dict[str, str]
]:
    """Enumerate admissible shared-repair configurations (<= 2 repairs -> <= 4 configs).

    Returns (configs, downtime closures per config, excluded repair reasons).
    """
    excluded: dict[str, str] = {}
    repairs = []
    for inst in sorted(pilot.instances.values(), key=lambda i: i.instance_id):
        if inst.category is not ActionCategory.shared_repair:
            continue
        why = instance_admissibility(inst, decision_at, planting, pilot)
        if why:
            excluded[inst.instance_id] = why
            continue
        if "delivery_factor_after" not in inst.parameters:
            excluded[inst.instance_id] = f"{inst.instance_id}: missing delivery_factor_after"
            continue
        repairs.append(inst)
    if len(repairs) > 2:
        raise ContextError(f"v2 allows at most two shared repairs per pilot, got {len(repairs)}")
    configs: list[SharedConfiguration] = []
    downtime: dict[str, list[tuple[str, datetime, datetime]]] = {}
    for k in range(len(repairs) + 1):
        for combo in itertools.combinations(repairs, k):
            cid = "cfg:base" if not combo else "cfg:" + "+".join(i.instance_id for i in combo)
            overrides: dict[str, float] = {}
            closures = []
            for inst in combo:
                for eid in inst.target_ids:
                    if eid in pilot.network.edges:
                        overrides[eid] = float(inst.parameters["delivery_factor_after"])
                        on = commissioned_on(inst, decision_at)
                        dd = int(inst.parameters.get("downtime_days", 0))
                        if dd > 0:
                            closures.append(
                                (
                                    eid,
                                    local_midnight_utc(on - timedelta(days=dd)),
                                    local_midnight_utc(on),
                                )
                            )
            configs.append(
                SharedConfiguration(
                    shared_configuration_id=cid,
                    repair_instance_ids=[i.instance_id for i in combo],
                    capex_pkr=sum(i.capex_pkr for i in combo),
                    seasonal_opex_pkr=sum(i.seasonal_opex_pkr for i in combo),
                    edge_delivery_factors=overrides,
                )
            )
            downtime[cid] = closures
    return configs, downtime, excluded


# --------------------------------------------------------------------------- intervals


def atomic_intervals(
    boundaries: Iterable[datetime], horizon: tuple[datetime, datetime]
) -> list[AtomicInterval]:
    """Smallest non-overlapping intervals induced by the given boundaries (T4.1)."""
    h0, h1 = to_utc(horizon[0]), to_utc(horizon[1])
    cuts = sorted({h0, h1, *(to_utc(b) for b in boundaries if h0 < to_utc(b) < h1)})
    return [
        AtomicInterval(interval_id=f"t{i:05d}", start=a, end=b)
        for i, (a, b) in enumerate(itertools.pairwise(cuts))
    ]


def interval_index(intervals: list[AtomicInterval]) -> dict[tuple[datetime, datetime], str]:
    return {(to_utc(i.start), to_utc(i.end)): i.interval_id for i in intervals}


def day_interval_id(d: date) -> str:
    return f"d{d.isoformat()}"
