"""Shared groundwater pumps (T4.5).

A pump is constrained across all fields that use it, never per field. Volume
caps: ``max_rate_m3_h x 24 h`` per local day (resource interval ``d<date>``)
and ``seasonal_cap_m3`` per season. Operating cost uses the declared decimal
``cost_per_m3_pkr`` (integer PKR, rounded up); energy is estimated only when
head and efficiency are declared (``rho g V H / (3.6e6 eta)``), never invented.
On-farm pump water is injected at the pump node and does not consume canal
capacity.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from aabflow.domain import units
from aabflow.domain.calendar import local_crop_date
from aabflow.domain.schemas import Asset, AssetKind, LedgerEvent, LedgerEventKind
from aabflow.water.validation import Residuals, exceeds

HOURS_PER_DAY = 24.0


class PumpError(ValueError):
    pass


@dataclass(frozen=True)
class PumpSpec:
    asset_id: str
    field_ids: frozenset[str]
    max_rate_m3_h: float
    seasonal_cap_m3: float | None
    cost_per_m3_pkr: str | None
    commissioned_on: date | None
    head_m: float | None = None
    efficiency: float | None = None
    quality_status: str = "unknown"

    @classmethod
    def from_asset(cls, a: Asset) -> PumpSpec:
        if a.kind is not AssetKind.pump:
            raise PumpError(f"{a.asset_id} is not a pump")
        if a.max_rate_m3_h is None:
            raise PumpError(f"pump {a.asset_id} lacks max_rate_m3_h")
        return cls(
            asset_id=a.asset_id,
            field_ids=frozenset(a.field_ids),
            max_rate_m3_h=a.max_rate_m3_h,
            seasonal_cap_m3=a.seasonal_cap_m3,
            cost_per_m3_pkr=a.cost_per_m3_pkr,
            commissioned_on=a.commissioned_at,
            head_m=a.head_m,
            efficiency=a.efficiency,
            quality_status=a.quality_status,
        )

    @property
    def daily_cap_m3(self) -> float:
        return self.max_rate_m3_h * HOURS_PER_DAY

    def cost_pkr(self, volume_m3: float) -> int:
        if self.cost_per_m3_pkr is None:
            raise PumpError(f"pump {self.asset_id} has no declared cost per m3")
        return units.spend_pkr(self.cost_per_m3_pkr, volume_m3)

    def energy_kwh(self, volume_m3: float) -> float | None:
        if self.head_m is None or self.efficiency is None:
            return None
        return units.pump_energy_kwh(volume_m3, self.head_m, self.efficiency)


def validate_pump_use(spec: PumpSpec, events: Iterable[LedgerEvent]) -> Residuals:
    """Shared-pump rules over *all* fields' abstraction events for this pump."""
    r = Residuals()
    for rule in ("pump_access", "pump_rate", "pump_seasonal_cap", "pump_cost", "commissioning"):
        r.check(rule)
    ev = [
        e
        for e in events
        if e.kind is LedgerEventKind.pump_abstraction and e.asset_id == spec.asset_id
    ]
    per_day: dict[date, float] = {}
    total = 0.0
    for e in ev:
        if e.field_id not in spec.field_ids:
            r.fail(
                "pump_access",
                e.volume_m3,
                [spec.asset_id, e.field_id or "?"],
                e.timestamp,
                f"field {e.field_id} has no access to pump {spec.asset_id}",
            )
        d = local_crop_date(e.timestamp)
        if spec.commissioned_on is not None and d < spec.commissioned_on:
            r.fail(
                "commissioning",
                e.volume_m3,
                [spec.asset_id],
                e.timestamp,
                f"pump used on {d} before commissioning {spec.commissioned_on}",
            )
        per_day[d] = per_day.get(d, 0.0) + e.volume_m3
        total += e.volume_m3
    for d, v in per_day.items():
        if exceeds(v, spec.daily_cap_m3):
            r.fail(
                "pump_rate",
                v - spec.daily_cap_m3,
                [spec.asset_id],
                None,
                f"{v:.1f} m3 on {d} exceeds {spec.daily_cap_m3:.1f} m3/day (shared across fields)",
            )
    if spec.seasonal_cap_m3 is not None and exceeds(total, spec.seasonal_cap_m3):
        r.fail(
            "pump_seasonal_cap",
            total - spec.seasonal_cap_m3,
            [spec.asset_id],
            None,
            f"seasonal abstraction {total:.1f} m3 exceeds cap {spec.seasonal_cap_m3:.1f} m3",
        )
    if total > 0 and spec.cost_per_m3_pkr is None:
        r.fail(
            "pump_cost", total, [spec.asset_id], None, "pump used without a declared cost per m3"
        )
    return r
