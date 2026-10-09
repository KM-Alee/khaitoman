"""T12.1 units group: thousandfold, area, and currency mistakes."""

import math
from decimal import Decimal

import pytest

from aabflow.domain import units as u


def test_one_mm_on_one_ha_is_ten_m3():
    assert u.depth_mm_to_volume_m3(1, 1) == 10.0
    assert u.volume_m3_to_depth_mm(750, 1) == 75.0


def test_tonnes_to_kg_and_production():
    assert u.t_ha_to_kg_ha(1) == 1000.0
    assert u.production_kg(2.5, 4000) == 10_000.0


def test_pond_footprint_subtracted_once_and_rejects_empty_field():
    assert u.cropped_area_ha(1.0, 500) == pytest.approx(0.95)
    with pytest.raises(u.UnitError):
        u.cropped_area_ha(0.05, 500)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "1"])
def test_nonfinite_or_wrong_type_rejected(bad):
    with pytest.raises(u.UnitError):
        u.depth_mm_to_volume_m3(bad, 1)


def test_fractions_and_delivery_factors():
    assert u.shortage_percent_to_fraction(22) == pytest.approx(0.22)
    with pytest.raises(u.UnitError):
        u.fraction(22)
    with pytest.raises(u.UnitError):
        u.delivery_factor(0)
    assert u.application_efficiency_to_aquacrop_percent(0.7) == pytest.approx(70.0)


def test_conservative_rounding_never_creates_feasibility():
    # 0.3 m³ is 3 quanta exactly despite binary float noise.
    assert u.consumption_quanta(0.3) == 3
    assert u.capacity_quanta(0.3) == 3
    assert u.consumption_quanta(0.31) == 4
    assert u.capacity_quanta(0.39) == 3
    assert u.credited_service_quanta(0.39) == 3
    assert u.required_service_quanta(0.31) == 4


def test_currency_uses_decimal_rates_and_integer_pkr():
    assert u.spend_pkr("12.5", 3) == 38  # 37.5 rounds up
    assert u.spend_pkr(Decimal("0.1"), 3) == 1
    with pytest.raises(u.UnitError):
        u.spend_pkr(12.5, 3)
    with pytest.raises(u.UnitError):
        u.pkr(1.0)


def test_pond_formulas():
    assert u.pond_evaporation_m3(0.8, 5, 1000) == pytest.approx(4.0)
    assert u.pond_rain_m3(10, 1000, 0.5) == pytest.approx(5.0)


def test_pump_energy():
    # 1000 m³ lifted 10 m at 50%: 1000*9.80665*1000*10/(3.6e6*0.5) ≈ 54.48 kWh
    assert u.pump_energy_kwh(1000, 10, 0.5) == pytest.approx(54.481, rel=1e-4)
