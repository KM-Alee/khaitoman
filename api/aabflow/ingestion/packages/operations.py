"""Roster, service reference, assets, interventions and soils for a pilot (T3.4, T4.3-T4.6, PRD §6).

All quantities here are *declared scenario assumptions* (no local records were
available). Each carries an evidence id whose record states the value, unit and
an editable range (``ASSUMPTIONS``). Rights stay ``verification="assumed"``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aabflow.domain.schemas import (
    ActionCategory,
    Asset,
    AssetKind,
    Edge,
    InterventionInstance,
    InterventionType,
    RightsBasis,
    RosterWindow,
    ServiceReference,
    SoilProfile,
)

from .network import NetworkBuild, path_factor

PKT = ZoneInfo("Asia/Karachi")
IRRIGATION_DEPTH_MM = 75.0
POND_SIZES = (("small", 0.5), ("medium", 1.0), ("large", 1.5))
POND_USABLE_DEPTH_M = 2.0
POND_FOOTPRINT_FACTOR = 1.35  # embankment/berm land per m² of water surface


@dataclass(frozen=True)
class SeasonCalendar:
    season_id: str
    crop: str
    start: date  # first roster day (planting-ready)
    end: date  # last roster day (harvest)
    closure: (
        tuple[date, date] | None
    )  # annual canal closure (assumed), inclusive start, exclusive end


SEASONS = (
    SeasonCalendar(
        "wheat-rabi-2024-25",
        "wheat",
        date(2024, 11, 15),
        date(2025, 4, 15),
        (date(2024, 12, 26), date(2025, 1, 25)),
    ),
    SeasonCalendar(
        "wheat-rabi-2026-27",
        "wheat",
        date(2026, 11, 15),
        date(2027, 4, 15),
        (date(2026, 12, 26), date(2027, 1, 25)),
    ),
    SeasonCalendar(
        "wheat-rabi-2027-28",
        "wheat",
        date(2027, 11, 15),
        date(2028, 4, 15),
        (date(2027, 12, 26), date(2028, 1, 25)),
    ),
    SeasonCalendar("cotton-kharif-2027", "cotton", date(2027, 5, 1), date(2027, 10, 31), None),
)


@dataclass(frozen=True)
class Assumption:
    evidence_id: str
    title: str
    value: float
    unit: str
    low: float
    high: float
    basis: str


def _a(eid, title, value, unit, low, high, basis):
    return Assumption(eid, title, value, unit, low, high, basis)


# Editable assumptions with ranges (evidence.json). Values are planning priors.
ASSUMPTIONS = {
    a.evidence_id: a
    for a in (
        _a(
            "asm:water-allowance",
            "Canal water allowance at the mogha",
            0.21,
            "L/s per ha CCA",
            0.15,
            0.30,
            "≈3 cusec per 1000 acres, a typical Punjab perennial-canal allowance; "
            "local design discharge not available",
        ),
        _a(
            "asm:warabandi-cycle",
            "Warabandi rotation length",
            168,
            "h",
            168,
            168,
            "Fixed weekly rotation (warabandi) with turn time proportional to field area",
        ),
        _a(
            "asm:canal-closure",
            "Annual Rabi canal closure",
            30,
            "days",
            15,
            40,
            "Late-December to late-January maintenance closure; exact dates vary by year",
        ),
        _a(
            "asm:reach-delivery",
            "Watercourse reach delivery factor (earthen)",
            0.86,
            "fraction",
            0.70,
            0.97,
            "Fractional conveyance loss per reach; uncalibrated, literature range "
            "for unlined Punjab watercourses",
        ),
        _a(
            "asm:parent-delivery",
            "Parent canal reach delivery factor",
            0.97,
            "fraction",
            0.93,
            0.99,
            "Short reach of a lined/large canal",
        ),
        _a(
            "asm:source-capacity",
            "Parent canal intake capacity available to the pilot",
            0.10,
            "m3/s",
            0.05,
            0.20,
            "Share of the distributary flow serving both watercourses",
        ),
        _a(
            "asm:app-eff-existing",
            "Existing field application efficiency",
            0.60,
            "fraction",
            0.45,
            0.70,
            "Basin/border irrigation on unlevelled fields",
        ),
        _a(
            "asm:app-eff-leveled",
            "Application efficiency after laser leveling",
            0.75,
            "fraction",
            0.65,
            0.85,
            "Laser land leveling evidence range",
        ),
        _a(
            "asm:leveling-cost",
            "Laser leveling service cost",
            14000,
            "PKR/ha",
            9000,
            22000,
            "Hired laser leveler, about 5,600 PKR/acre; quote not obtained",
        ),
        _a(
            "asm:leveling-lead",
            "Leveling lead time",
            10,
            "days",
            5,
            21,
            "Service booking plus work; must finish before planting",
        ),
        _a(
            "asm:pond-cost",
            "Farm pond earthwork cost",
            320,
            "PKR/m3 storage",
            200,
            600,
            "Unlined excavated pond with embankment; plus fixed 40,000 PKR inlet/outlet works",
        ),
        _a(
            "asm:pond-fixed-cost",
            "Farm pond fixed works",
            40000,
            "PKR",
            20000,
            80000,
            "Inlet, outlet and small structures",
        ),
        _a(
            "asm:pond-lead",
            "Pond construction lead time",
            90,
            "days",
            60,
            120,
            "Procurement plus construction before commissioning",
        ),
        _a(
            "asm:pond-seepage",
            "Pond seepage rate",
            4.0,
            "mm/day",
            2.0,
            10.0,
            "Unlined pond in silt loam",
        ),
        _a(
            "asm:pond-kevap",
            "Open-water evaporation coefficient on ET0",
            1.0,
            "ratio",
            0.8,
            1.2,
            "k_evap applied to FAO ET0 (T4.4)",
        ),
        _a("asm:pond-upkeep", "Pond annual upkeep", 15000, "PKR/year", 5000, 30000, "Desilting"),
        _a(
            "asm:lining-cost",
            "Watercourse lining cost",
            6500,
            "PKR/m",
            4000,
            10000,
            "Brick/concrete lining per metre; partial-lining programme scale",
        ),
        _a(
            "asm:lining-factor",
            "Reach delivery factor after lining",
            0.95,
            "fraction",
            0.92,
            0.98,
            "Lined watercourse reach",
        ),
        _a(
            "asm:lining-lead",
            "Repair lead time",
            120,
            "days",
            90,
            180,
            "Design, procurement and construction",
        ),
        _a(
            "asm:lining-downtime",
            "Repair construction downtime",
            14,
            "days",
            7,
            30,
            "Reach closed while lining is built",
        ),
        _a(
            "asm:pump-rate",
            "Existing shared tubewell maximum rate",
            100.0,
            "m3/h",
            60.0,
            140.0,
            "≈1 cusec diesel tubewell",
        ),
        _a(
            "asm:pump-cost",
            "Tubewell operating cost",
            8.5,
            "PKR/m3",
            4.0,
            14.0,
            "Diesel at ~270 PKR/L, ~3 L/h at 100 m3/h",
        ),
        _a(
            "asm:pump-cap",
            "Seasonal groundwater cap for the shared tubewell",
            40000.0,
            "m3",
            20000.0,
            80000.0,
            "Scenario aquifer-use cap; no permit record",
        ),
        _a("asm:pump-head", "Tubewell total head", 20.0, "m", 12.0, 35.0, "Water table depth"),
        _a(
            "asm:pump-eff",
            "Tubewell pumping efficiency",
            0.45,
            "fraction",
            0.30,
            0.60,
            "Diesel set",
        ),
        _a(
            "asm:soil-archetypes",
            "Soil archetypes by watercourse",
            2,
            "classes",
            2,
            3,
            "AquaCrop predefined SiltLoam/Loam priors for Rechna doab alluvium; no local "
            "soil survey",
        ),
        _a(
            "asm:initial-soil-water",
            "Initial soil water at simulation start",
            50,
            "% TAW",
            30,
            80,
            "Post-kharif/pre-rabi depletion assumption",
        ),
    )
}


def _pkt(d: date, t: time = time(6, 0)) -> datetime:
    return datetime.combine(d, t, tzinfo=PKT).astimezone(UTC)


def closure_interval(cal: SeasonCalendar) -> tuple[datetime, datetime] | None:
    if cal.closure is None:
        return None
    return (_pkt(cal.closure[0]), _pkt(cal.closure[1]))


def watercourse_rate_m3_s(cca_ha: float) -> float:
    return ASSUMPTIONS["asm:water-allowance"].value * 1e-3 * cca_ha


def build_roster(
    pilot_id: str,
    net: NetworkBuild,
    field_area_ha: dict[str, float],
    seasons: tuple[SeasonCalendar, ...] = SEASONS,
) -> dict[str, list[RosterWindow]]:
    """Fixed, exclusive weekly warabandi windows per watercourse (head → tail)."""
    cycle = timedelta(hours=ASSUMPTIONS["asm:warabandi-cycle"].value)
    out: dict[str, list[RosterWindow]] = {}
    for cal in seasons:
        wins: list[RosterWindow] = []
        for wc, fids in net.watercourse_fields.items():
            cca = sum(field_area_ha[f] for f in fids)
            rate = round(watercourse_rate_m3_s(cca), 6)
            t0 = _pkt(cal.start)
            end = _pkt(cal.end + timedelta(days=1))
            k = 0
            while t0 < end:
                t = t0
                for fid in fids:
                    dur = cycle * (field_area_ha[fid] / cca)
                    s, e = t, min(t + dur, end)
                    t = t + dur
                    if s >= end:
                        break
                    k += 1
                    wins.append(
                        RosterWindow(
                            window_id=f"{pilot_id}:{cal.season_id}:{wc}:w{k:04d}",
                            field_id=fid,
                            outlet_node_id=net.mogha_of[wc],
                            start=s.replace(microsecond=0),
                            end=e.replace(microsecond=0),
                            basis=RightsBasis.time,
                            rate_m3_s=rate,
                            accounting_boundary="outlet",
                            verification="assumed",
                            source_rule=(
                                "weekly warabandi, head-to-tail order, turn time ∝ field area, "
                                f"watercourse rate {rate} m3/s from allowance "
                                f"{ASSUMPTIONS['asm:water-allowance'].value} L/s/ha (assumed)"
                            ),
                        )
                    )
                t0 = t0 + cycle
        out[cal.season_id] = wins
    return out


def _overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> float:
    return max(0.0, (min(a[1], b[1]) - max(a[0], b[0])).total_seconds())


def build_service_reference(
    roster: dict[str, list[RosterWindow]],
    net: NetworkBuild,
    edges: list[Edge],
    seasons: tuple[SeasonCalendar, ...] = SEASONS,
) -> list[ServiceReference]:
    """Fixed full-supply reference: Σ rate×open seconds × nominal path factor to the field outlet.

    Closed periods (declared closure) deliver nothing and are excluded. Time-derived;
    the UI labels the ratio "receipt / reference allowance".
    """
    cal_by = {c.season_id: c for c in seasons}
    refs = []
    for sid, wins in roster.items():
        clo = closure_interval(cal_by[sid])
        tot: dict[str, float] = {}
        for w in wins:
            secs = (w.end - w.start).total_seconds()
            if clo:
                secs -= _overlaps((w.start, w.end), clo)
            f = path_factor(edges, w.outlet_node_id, net.field_outlet[w.field_id])
            tot[w.field_id] = tot.get(w.field_id, 0.0) + w.rate_m3_s * secs * f
        for fid in sorted(tot):
            refs.append(
                ServiceReference(
                    field_id=fid,
                    season_id=sid,
                    reference_receipt_m3=round(tot[fid], 3),
                    basis=RightsBasis.time,
                    evidence_ids=[
                        "asm:water-allowance",
                        "asm:warabandi-cycle",
                        "asm:canal-closure",
                        "asm:reach-delivery",
                    ],
                )
            )
    return refs


def pond_geometry(field_area_m2: float, irrigations: float) -> dict[str, float]:
    """Pond sized to hold ``irrigations`` × 75 mm over the field (T4.4)."""
    v = irrigations * IRRIGATION_DEPTH_MM / 1000.0 * field_area_m2
    surface = v / POND_USABLE_DEPTH_M
    return {
        "usable_capacity_m3": round(v, 2),
        "surface_area_m2": round(surface, 2),
        "footprint_m2": round(surface * POND_FOOTPRINT_FACTOR, 2),
    }


def _pond_ops(geom: dict[str, float]) -> dict[str, float]:
    v, s = geom["usable_capacity_m3"], geom["surface_area_m2"]
    return {
        "max_fill_m3_day": round(v, 2),
        "max_release_m3_day": round(min(v, 1296.0), 2),  # ~15 L/s outlet/lift
        "seepage_m3_day": round(ASSUMPTIONS["asm:pond-seepage"].value / 1000.0 * s, 3),
        "k_evap": ASSUMPTIONS["asm:pond-kevap"].value,
        "rain_capture_fraction": 1.0,
    }


@dataclass
class AssetBuild:
    assets: list[Asset]
    pond_field: str
    pump_fields: list[str]
    pond_id: str
    pump_id: str


def build_assets(pilot_id: str, net: NetworkBuild, field_area_m2: dict[str, float]) -> AssetBuild:
    wc1 = net.watercourse_fields["wc1"]
    middle = [f for f in wc1 if net.field_group[f] == "middle"]
    pond_field = max(middle, key=lambda f: (field_area_m2[f], f))
    g = pond_geometry(field_area_m2[pond_field], 1.0)
    ops = _pond_ops(g)
    pond_id = f"{pilot_id}:asset-pond-existing"
    pond = Asset(
        asset_id=pond_id,
        kind=AssetKind.pond,
        existing=True,
        field_ids=[pond_field],
        node_id=net.field_outlet[pond_field],
        commissioned_at=date(2019, 6, 1),
        usable_capacity_m3=g["usable_capacity_m3"],
        surface_area_m2=g["surface_area_m2"],
        footprint_m2=g["footprint_m2"],
        initial_inventory_m3=round(0.3 * g["usable_capacity_m3"], 2),
        max_fill_m3_day=ops["max_fill_m3_day"],
        max_release_m3_day=ops["max_release_m3_day"],
        seepage_m3_day=ops["seepage_m3_day"],
        k_evap=ops["k_evap"],
        rain_capture_fraction=1.0,
        annual_upkeep_pkr=int(ASSUMPTIONS["asm:pond-upkeep"].value),
        evidence_ids=[
            "asm:existing-assets",
            "asm:pond-seepage",
            "asm:pond-kevap",
            "asm:pond-upkeep",
        ],
    )
    pump_fields = [f for f in wc1 if net.field_group[f] in ("middle", "tail")]
    tail_node = net.field_outlet[next(f for f in wc1 if net.field_group[f] == "tail")]
    pump_id = f"{pilot_id}:asset-pump-existing"
    pump = Asset(
        asset_id=pump_id,
        kind=AssetKind.pump,
        existing=True,
        field_ids=sorted(pump_fields),
        node_id=tail_node,
        commissioned_at=date(2015, 3, 1),
        max_rate_m3_h=ASSUMPTIONS["asm:pump-rate"].value,
        seasonal_cap_m3=ASSUMPTIONS["asm:pump-cap"].value,
        cost_per_m3_pkr=f"{ASSUMPTIONS['asm:pump-cost'].value:.2f}",
        head_m=ASSUMPTIONS["asm:pump-head"].value,
        efficiency=ASSUMPTIONS["asm:pump-eff"].value,
        quality_status="unknown",
        annual_upkeep_pkr=25000,
        evidence_ids=[
            "asm:existing-assets",
            "asm:pump-rate",
            "asm:pump-cost",
            "asm:pump-cap",
            "asm:pump-head",
            "asm:pump-eff",
        ],
    )
    return AssetBuild([pond, pump], pond_field, sorted(pump_fields), pond_id, pump_id)


INTERVENTION_TYPES = [
    InterventionType(
        type_id="timing-existing-assets",
        category=ActionCategory.timing,
        effect_model="ledger-timing",
        effect_model_version="1",
        applicability_schema={"targets": "existing pond/pump asset ids"},
        required_parameters=[],
    ),
    InterventionType(
        type_id="laser-leveling",
        category=ActionCategory.leveling,
        effect_model="application-efficiency-change",
        effect_model_version="1",
        applicability_schema={"targets": "one field", "before": "planting"},
        required_parameters=["application_efficiency_after"],
    ),
    InterventionType(
        type_id="farm-pond",
        category=ActionCategory.pond,
        effect_model="pond-storage",
        effect_model_version="1",
        applicability_schema={
            "targets": "one field",
            "before": "planting",
            "sizing": "irrigations of 75 mm over the field",
        },
        required_parameters=[
            "irrigations_held",
            "usable_capacity_m3",
            "surface_area_m2",
            "footprint_m2",
        ],
    ),
    InterventionType(
        type_id="watercourse-lining",
        category=ActionCategory.shared_repair,
        effect_model="edge-delivery-factor",
        effect_model_version="1",
        applicability_schema={"targets": "one assumed watercourse reach edge"},
        required_parameters=["delivery_factor_after", "downtime_days"],
    ),
    InterventionType(
        type_id="pump-supplement",
        category=ActionCategory.pump_supplement,
        effect_model="groundwater-injection",
        effect_model_version="1",
        applicability_schema={"targets": "one existing pump asset"},
        required_parameters=[],
    ),
]


def _pond_fields(
    net: NetworkBuild, field_area_m2: dict[str, float], exclude: str, n: int
) -> list[str]:
    """Pond-eligible fields: largest fields per watercourse group, round-robin, excluding the existing pond's."""
    picks: list[str] = []
    by_group: dict[tuple[str, str], list[str]] = {}
    for f, g in net.field_group.items():
        if f == exclude:
            continue
        by_group.setdefault((net.field_watercourse[f], g), []).append(f)
    for v in by_group.values():
        v.sort(key=lambda f: (-field_area_m2[f], f))
    keys = sorted(by_group)
    while len(picks) < n and any(by_group.values()):
        for k in keys:
            if by_group[k] and len(picks) < n:
                picks.append(by_group[k].pop(0))
    return sorted(picks)


def build_interventions(
    pilot_id: str,
    net: NetworkBuild,
    edges: list[Edge],
    field_area_m2: dict[str, float],
    assets: AssetBuild,
    reach_lengths_m: dict[str, float],
    n_pond_fields: int = 10,
) -> tuple[list[InterventionType], list[InterventionInstance]]:
    A = ASSUMPTIONS
    inst: list[InterventionInstance] = []
    inst.append(
        InterventionInstance(
            instance_id=f"{pilot_id}:timing:existing-assets",
            type_id="timing-existing-assets",
            category=ActionCategory.timing,
            target_ids=[assets.pond_id, assets.pump_id],
            parameters={},
            capex_pkr=0,
            evidence_ids=["asm:existing-assets"],
        )
    )
    for fid in sorted(field_area_m2):
        ha = field_area_m2[fid] / 10_000.0
        inst.append(
            InterventionInstance(
                instance_id=f"{fid}:leveling",
                type_id="laser-leveling",
                category=ActionCategory.leveling,
                target_ids=[fid],
                parameters={"application_efficiency_after": A["asm:app-eff-leveled"].value},
                capex_pkr=max(1, math.ceil(ha * A["asm:leveling-cost"].value)),
                procurement_delay_days=4,
                lead_time_days=int(A["asm:leveling-lead"].value),
                evidence_ids=["asm:leveling-cost", "asm:leveling-lead", "asm:app-eff-leveled"],
            )
        )
    for fid in _pond_fields(net, field_area_m2, assets.pond_field, n_pond_fields):
        for size, irr in POND_SIZES:
            g = pond_geometry(field_area_m2[fid], irr)
            capex = math.ceil(
                A["asm:pond-fixed-cost"].value + A["asm:pond-cost"].value * g["usable_capacity_m3"]
            )
            inst.append(
                InterventionInstance(
                    instance_id=f"{fid}:pond-{size}",
                    type_id="farm-pond",
                    category=ActionCategory.pond,
                    target_ids=[fid],
                    parameters={
                        "irrigations_held": irr,
                        "irrigation_depth_mm": IRRIGATION_DEPTH_MM,
                        **g,
                        **_pond_ops(g),
                    },
                    mutually_exclusive_group=f"{fid}:pond",
                    capex_pkr=capex,
                    procurement_delay_days=21,
                    lead_time_days=int(A["asm:pond-lead"].value),
                    evidence_ids=[
                        "asm:pond-cost",
                        "asm:pond-fixed-cost",
                        "asm:pond-lead",
                        "asm:pond-seepage",
                        "asm:pond-kevap",
                    ],
                )
            )
    # ≤2 shared repairs: the downstream reaches that set tail receipts.
    repair_edges = [net.reach_edges["wc1"][1], net.reach_edges["wc2"][2]]
    for eid in repair_edges:
        length = reach_lengths_m[eid]
        inst.append(
            InterventionInstance(
                instance_id=f"{eid}:repair",
                type_id="watercourse-lining",
                category=ActionCategory.shared_repair,
                target_ids=[eid],
                parameters={
                    "delivery_factor_after": A["asm:lining-factor"].value,
                    "downtime_days": int(A["asm:lining-downtime"].value),
                    "reach_length_m": round(length, 1),
                },
                capex_pkr=math.ceil(length * A["asm:lining-cost"].value),
                procurement_delay_days=30,
                lead_time_days=int(A["asm:lining-lead"].value),
                shared=True,
                evidence_ids=[
                    "asm:lining-cost",
                    "asm:lining-factor",
                    "asm:lining-lead",
                    "asm:lining-downtime",
                ],
            )
        )
    inst.append(
        InterventionInstance(
            instance_id=f"{assets.pump_id}:supplement",
            type_id="pump-supplement",
            category=ActionCategory.pump_supplement,
            target_ids=[assets.pump_id],
            parameters={},
            capex_pkr=0,
            shared=True,
            evidence_ids=["asm:pump-cost", "asm:pump-cap", "asm:pump-rate"],
        )
    )
    return INTERVENTION_TYPES, inst


SOIL_ARCHETYPES = {
    "wc1": ("SiltLoam", "Rechna doab silt-loam alluvium (prior)"),
    "wc2": ("Loam", "Rechna doab loam alluvium (prior)"),
}


def build_soils(pilot_id: str, net: NetworkBuild) -> tuple[list[SoilProfile], dict[str, str]]:
    profiles = []
    field_soil = {}
    for wc, (cls, arche) in SOIL_ARCHETYPES.items():
        sid = f"{pilot_id}:soil-{cls.lower()}"
        profiles.append(
            SoilProfile(
                soil_profile_id=sid,
                engine_soil_type=cls,
                archetype=arche,
                initial_water="pct_taw:50",
                evidence_ids=["asm:soil-archetypes", "asm:initial-soil-water"],
                limitations=[
                    "AquaCrop predefined class; not a measured hydraulic profile",
                    "assigned per watercourse command area, not per field survey",
                ],
            )
        )
        for f in net.watercourse_fields[wc]:
            field_soil[f] = sid
    return profiles, field_soil
