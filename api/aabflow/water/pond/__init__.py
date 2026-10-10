"""Pond inventory chronology (T4.4).

    S_next = S_start + canal_fill + pump_fill + direct_rain
             - released_to_field - evaporation - seepage - explicit_spill
    0 <= S at every event <= usable_capacity

Events are processed in ``(timestamp, explicit_order, event_id)`` order. A
release before the receipt that fills it (Monday use of Friday water) drives
inventory negative and is rejected; a fill above capacity at any event is
rejected even if a later release would bring the period total back in range.

Daily forcing apportionment (documented, not an observed hourly series): pond
rain, evaporation and seepage for a local day are booked at the end of that day
(next local midnight) in the order rain(10) -> automatic overflow spill(15) ->
evaporation(20) -> seepage(30), after that day's controlled fills/releases.
Evaporation = ``k_evap x ET0 x surface_area / 1000`` and rain =
``P x surface_area x capture / 1000`` (constant-area approximation); each loss
is capped by the inventory available at its event, so losses never create
negative storage and are never used as balancing residuals.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from aabflow.domain import units
from aabflow.domain.calendar import PKT, local_crop_date, to_utc
from aabflow.domain.schemas import LedgerEvent, LedgerEventKind
from aabflow.water.validation import Residuals, exceeds

INFLOW = {LedgerEventKind.pond_fill, LedgerEventKind.pond_rain}
OUTFLOW = {
    LedgerEventKind.pond_release,
    LedgerEventKind.pond_evaporation,
    LedgerEventKind.pond_seepage,
    LedgerEventKind.pond_spill,
}
LOSSES = {LedgerEventKind.pond_evaporation, LedgerEventKind.pond_seepage}
ORDER_RAIN, ORDER_SPILL, ORDER_EVAP, ORDER_SEEP = 10, 15, 20, 30


@dataclass(frozen=True)
class PondSpec:
    asset_id: str
    usable_capacity_m3: float
    surface_area_m2: float
    initial_inventory_m3: float = 0.0
    k_evap: float = 1.0
    rain_capture_fraction: float = 1.0
    seepage_m3_day: float = 0.0
    max_fill_m3_day: float | None = None
    max_release_m3_day: float | None = None
    footprint_m2: float = 0.0
    existing: bool = True
    commissioned_on: date | None = None

    def __post_init__(self) -> None:
        units.nonnegative(self.usable_capacity_m3, "usable_capacity_m3")
        units.nonnegative(self.surface_area_m2, "surface_area_m2")
        if self.initial_inventory_m3 > self.usable_capacity_m3:
            raise ValueError(f"{self.asset_id}: initial inventory exceeds usable capacity")
        if self.footprint_m2 and self.surface_area_m2 > self.footprint_m2 + 1e-9:
            raise ValueError(f"{self.asset_id}: water surface larger than footprint")


@dataclass
class PondTrace:
    events: list[LedgerEvent]
    inventory_after: list[float]  # aligned with events
    initial_m3: float
    terminal_m3: float
    residuals: Residuals
    totals: dict[str, float] = field(default_factory=dict)
    peak_m3: float = 0.0


def sort_key(e: LedgerEvent) -> tuple:
    return (to_utc(e.timestamp), e.explicit_order, e.event_id)


def chronology(
    events: Iterable[LedgerEvent],
    capacity_m3: float,
    initial_m3: float,
    asset_id: str,
    *,
    max_fill_m3_day: float | None = None,
    max_release_m3_day: float | None = None,
) -> PondTrace:
    """Validate an explicit event list (no exogenous generation)."""
    ev = sorted((e for e in events if e.asset_id == asset_id), key=sort_key)
    r = Residuals()
    for rule in ("pond_capacity", "pond_nonnegative", "pond_loss_bound", "event_order"):
        r.check(rule)
    s = units.nonnegative(initial_m3, "initial_m3")
    if exceeds(s, capacity_m3):
        r.fail(
            "pond_capacity", s - capacity_m3, [asset_id], detail="initial inventory above capacity"
        )
    after: list[float] = []
    totals = {k.value: 0.0 for k in INFLOW | OUTFLOW}
    fill_day: dict[date, float] = {}
    rel_day: dict[date, float] = {}
    peak = s
    for k, e in enumerate(ev):
        v = units.nonnegative(e.volume_m3, f"{e.event_id}.volume_m3")
        if e.kind in INFLOW:
            s += v
        elif e.kind in OUTFLOW:
            if e.kind in LOSSES and exceeds(v, s):
                r.fail(
                    "pond_loss_bound",
                    v - s,
                    [asset_id, e.event_id],
                    e.timestamp,
                    f"{e.kind.value} {v:.3f} m3 exceeds available inventory {s:.3f} m3",
                )
            s -= v
        else:
            r.fail(
                "event_order", 0.0, [e.event_id], e.timestamp, f"non-pond event {e.kind} on pond"
            )
            continue
        totals[e.kind.value] += v
        if e.kind is LedgerEventKind.pond_fill:
            d = local_crop_date(e.timestamp)
            fill_day[d] = fill_day.get(d, 0.0) + v
        if e.kind is LedgerEventKind.pond_release:
            d = local_crop_date(e.timestamp)
            rel_day[d] = rel_day.get(d, 0.0) + v
        if exceeds(0.0, s):
            r.fail(
                "pond_nonnegative",
                -s,
                [asset_id, e.event_id],
                e.timestamp,
                f"inventory {s:.3f} m3 after {e.kind.value}: water used before it was received",
            )
        # Automatic overflow: rain followed at the same instant by its explicit spill
        # is one physical step; capacity is checked after the spill.
        overflow_step = (
            e.kind is LedgerEventKind.pond_rain
            and k + 1 < len(ev)
            and ev[k + 1].kind is LedgerEventKind.pond_spill
            and to_utc(ev[k + 1].timestamp) == to_utc(e.timestamp)
        )
        if exceeds(s, capacity_m3) and not overflow_step:
            r.fail(
                "pond_capacity",
                s - capacity_m3,
                [asset_id, e.event_id],
                e.timestamp,
                f"inventory {s:.3f} m3 exceeds usable capacity {capacity_m3:.3f} m3",
            )
        if not overflow_step:
            peak = max(peak, s)
        after.append(s)
    if max_fill_m3_day is not None:
        r.check("pond_fill_rate")
        for d, v in fill_day.items():
            if exceeds(v, max_fill_m3_day):
                r.fail("pond_fill_rate", v - max_fill_m3_day, [asset_id], None, f"fill on {d}")
    if max_release_m3_day is not None:
        r.check("pond_release_rate")
        for d, v in rel_day.items():
            if exceeds(v, max_release_m3_day):
                r.fail(
                    "pond_release_rate", v - max_release_m3_day, [asset_id], None, f"release on {d}"
                )
    return PondTrace(ev, after, initial_m3, s, r, totals, peak)


def day_end_utc(d: date) -> datetime:
    return to_utc(datetime(d.year, d.month, d.day, tzinfo=PKT) + timedelta(days=1))


def exogenous_events(
    spec: PondSpec,
    controlled: list[LedgerEvent],
    weather: Mapping[date, tuple[float, float]],  # date -> (precip_mm, et0_mm)
    days: list[date],
    *,
    active_from: date | None = None,
) -> tuple[list[LedgerEvent], PondTrace]:
    """Generate weather-dependent rain/spill/evaporation/seepage and validate the whole trace.

    ``active_from``: pond exists (commissioned) from this date; exogenous terms
    start then. Returns (exogenous events, trace over controlled + exogenous).
    """
    ctrl = sorted((e for e in controlled if e.asset_id == spec.asset_id), key=sort_key)
    out: list[LedgerEvent] = []
    s = spec.initial_inventory_m3
    i = 0
    for d in days:
        end = day_end_utc(d)
        while i < len(ctrl) and to_utc(ctrl[i].timestamp) < end:
            e = ctrl[i]
            s += e.volume_m3 if e.kind in INFLOW else -e.volume_m3
            i += 1
        if active_from is not None and d < active_from:
            continue
        p, et0 = weather.get(d, (0.0, 0.0))
        rain = units.pond_rain_m3(p, spec.surface_area_m2, spec.rain_capture_fraction)
        tag = f"{spec.asset_id}:{d.isoformat()}"
        if rain > 0:
            out.append(_ev(f"rain:{tag}", end, ORDER_RAIN, LedgerEventKind.pond_rain, rain, spec))
            s += rain
            if s > spec.usable_capacity_m3:
                spill = s - spec.usable_capacity_m3
                out.append(
                    _ev(f"spill:{tag}", end, ORDER_SPILL, LedgerEventKind.pond_spill, spill, spec)
                )
                s -= spill
        avail = max(s, 0.0)
        evap = min(units.pond_evaporation_m3(spec.k_evap, et0, spec.surface_area_m2), avail)
        if evap > 0:
            out.append(
                _ev(f"evap:{tag}", end, ORDER_EVAP, LedgerEventKind.pond_evaporation, evap, spec)
            )
            s -= evap
        seep = min(spec.seepage_m3_day, max(s, 0.0))
        if seep > 0:
            out.append(
                _ev(f"seep:{tag}", end, ORDER_SEEP, LedgerEventKind.pond_seepage, seep, spec)
            )
            s -= seep
    trace = chronology(
        ctrl + out,
        spec.usable_capacity_m3,
        spec.initial_inventory_m3,
        spec.asset_id,
        max_fill_m3_day=spec.max_fill_m3_day,
        max_release_m3_day=spec.max_release_m3_day,
    )
    return out, trace


def _ev(
    eid: str, ts: datetime, order: int, kind: LedgerEventKind, v: float, spec: PondSpec
) -> LedgerEvent:
    return LedgerEvent(
        event_id=eid,
        timestamp=ts,
        explicit_order=order,
        kind=kind,
        volume_m3=v,
        asset_id=spec.asset_id,
    )


def size_for_irrigations(
    irrigations: float, cropped_area_ha: float, depth_mm: float = 75.0, usable_depth_m: float = 1.5
) -> tuple[float, float, float]:
    """Pond sized by the irrigations it holds (T4.4): (volume m3, surface m2, footprint m2).

    Footprint adds a 2 m embankment ring around a square water surface.
    """
    vol = units.depth_mm_to_volume_m3(irrigations * depth_mm, cropped_area_ha)
    surface = vol / usable_depth_m
    side = surface**0.5
    footprint = (side + 4.0) ** 2
    return vol, surface, footprint
