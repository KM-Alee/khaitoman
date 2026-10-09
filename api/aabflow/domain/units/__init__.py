"""Canonical unit conversions and conservative integer scaling (T3.2, T6.2).

Physical quantities stay float64 at original precision. Money uses Decimal
rates and integer PKR. Solver coefficients are integers in a named quantum,
rounded so that they can create false infeasibility but never false
feasibility.
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

M3_PER_MM_HA = 10.0  # 1 mm over 1 ha = 10 m³
M2_PER_HA = 10_000.0
KG_PER_TONNE = 1000.0
DEFAULT_WATER_QUANTUM_M3 = 0.1
DEFAULT_PRODUCTION_QUANTUM_KG = 0.1


class UnitError(ValueError):
    """A quantity is nonfinite, out of range, or in the wrong unit."""


def finite(value: float, name: str = "value") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise UnitError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def nonnegative(value: float, name: str = "value") -> float:
    v = finite(value, name)
    if v < 0:
        raise UnitError(f"{name} must be >= 0, got {v}")
    return v


def fraction(value: float, name: str = "fraction") -> float:
    """Domain fractions live in [0, 1]; never percentages."""
    v = finite(value, name)
    if not 0.0 <= v <= 1.0:
        raise UnitError(f"{name} must be in [0, 1], got {v}")
    return v


def delivery_factor(value: float, name: str = "delivery_factor") -> float:
    """Edge delivery factors are in (0, 1] (T2.3)."""
    v = finite(value, name)
    if not 0.0 < v <= 1.0:
        raise UnitError(f"{name} must be in (0, 1], got {v}")
    return v


# --- water, area, yield ----------------------------------------------------

def depth_mm_to_volume_m3(depth_mm: float, area_ha: float) -> float:
    return nonnegative(depth_mm, "depth_mm") * nonnegative(area_ha, "area_ha") * M3_PER_MM_HA


def volume_m3_to_depth_mm(volume_m3: float, area_ha: float) -> float:
    area = nonnegative(area_ha, "area_ha")
    if area == 0:
        raise UnitError("cannot convert volume to depth over zero area")
    return nonnegative(volume_m3, "volume_m3") / (area * M3_PER_MM_HA)


def m2_to_ha(area_m2: float) -> float:
    return nonnegative(area_m2, "area_m2") / M2_PER_HA


def ha_to_m2(area_ha: float) -> float:
    return nonnegative(area_ha, "area_ha") * M2_PER_HA


def cropped_area_ha(gross_area_ha: float, new_pond_footprint_m2: float = 0.0) -> float:
    """Gross area minus a newly built pond footprint, subtracted once (T4.4)."""
    area = nonnegative(gross_area_ha, "gross_area_ha") - m2_to_ha(new_pond_footprint_m2)
    if area <= 0:
        raise UnitError(f"pond footprint leaves no cropped area ({area:.6f} ha)")
    return area


def t_ha_to_kg_ha(yield_t_ha: float) -> float:
    return nonnegative(yield_t_ha, "yield_t_ha") * KG_PER_TONNE


def production_kg(cropped_ha: float, yield_kg_ha: float) -> float:
    return nonnegative(cropped_ha, "cropped_area_ha") * nonnegative(yield_kg_ha, "yield_kg_ha")


def flow_to_max_volume_m3(rate_m3_s: float, seconds: float) -> float:
    return nonnegative(rate_m3_s, "rate_m3_s") * nonnegative(seconds, "seconds")


def shortage_percent_to_fraction(percent: float) -> float:
    """UI display conversion only; the API takes the fraction."""
    return fraction(finite(percent, "percent") / 100.0, "uniform_reduction_fraction")


def application_efficiency_to_aquacrop_percent(eff_fraction: float) -> float:
    """AquaCrop AppEff is a percent; the domain uses a fraction (T3.2)."""
    return fraction(eff_fraction, "application_efficiency") * 100.0


# --- ponds and pumps -------------------------------------------------------

def pond_evaporation_m3(k_evap: float, et0_mm: float, surface_area_m2: float) -> float:
    """Open-water evaporation from ET0 via a declared coefficient (T4.4)."""
    return nonnegative(k_evap, "k_evap") * nonnegative(et0_mm, "et0_mm") * nonnegative(surface_area_m2, "surface_area_m2") / 1000.0


def pond_rain_m3(rain_mm: float, surface_area_m2: float, capture_fraction: float) -> float:
    return nonnegative(rain_mm, "rain_mm") * nonnegative(surface_area_m2, "surface_area_m2") * fraction(capture_fraction, "capture_fraction") / 1000.0


def pump_energy_kwh(volume_m3: float, head_m: float, efficiency: float) -> float:
    """rho*g*V*H / (3.6e6*eta) (T4.5)."""
    eta = fraction(efficiency, "pump_efficiency")
    if eta == 0:
        raise UnitError("pump efficiency must be > 0")
    return 1000.0 * 9.80665 * nonnegative(volume_m3, "volume_m3") * nonnegative(head_m, "head_m") / (3.6e6 * eta)


# --- conservative integer scaling (T6.2) -----------------------------------

def _ratio(value: float, quantum: float) -> Decimal:
    q = Decimal(repr(nonnegative(quantum, "quantum")))
    if q == 0:
        raise UnitError("quantum must be > 0")
    return Decimal(repr(nonnegative(value, "value"))) / q


def consumption_quanta(value: float, quantum: float = DEFAULT_WATER_QUANTUM_M3) -> int:
    """Resource use rounds up."""
    return int(_ratio(value, quantum).to_integral_value(ROUND_CEILING))


def capacity_quanta(value: float, quantum: float = DEFAULT_WATER_QUANTUM_M3) -> int:
    """Resource upper bounds round down."""
    return int(_ratio(value, quantum).to_integral_value(ROUND_FLOOR))


def credited_service_quanta(value: float, quantum: float = DEFAULT_WATER_QUANTUM_M3) -> int:
    """Credited receipts for lower-bound service checks round down."""
    return int(_ratio(value, quantum).to_integral_value(ROUND_FLOOR))


def required_service_quanta(value: float, quantum: float = DEFAULT_WATER_QUANTUM_M3) -> int:
    """Required service amounts round up."""
    return int(_ratio(value, quantum).to_integral_value(ROUND_CEILING))


# --- money (T3.2): Decimal rates, integer PKR ------------------------------

def decimal_rate(rate: str | Decimal) -> Decimal:
    """Rates arrive as decimal strings (PKR/kg, PKR/m³); floats are rejected."""
    if isinstance(rate, float):
        raise UnitError("currency rates must be decimal strings, not float")
    d = Decimal(rate)
    if not d.is_finite() or d < 0:
        raise UnitError(f"rate must be a finite nonnegative decimal, got {rate!r}")
    return d


def spend_pkr(rate: str | Decimal, quantity: float) -> int:
    """Calculated spend in integer PKR, rounded up for feasibility checks."""
    total = decimal_rate(rate) * Decimal(repr(nonnegative(quantity, "quantity")))
    return int(total.to_integral_value(ROUND_CEILING))


def pkr(amount: int) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise UnitError(f"PKR amounts are nonnegative integers, got {amount!r}")
    return amount
