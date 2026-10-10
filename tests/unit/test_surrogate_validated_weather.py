"""Held-out weather validation never relaxes irrigation or unknown weather domains.

Labelled TEST FIXTURE metadata below; no model fitting or crop simulation.
"""

from types import SimpleNamespace

from aabflow.surrogate import domain
from aabflow.surrogate.features import FEATURE_VERSION


def test_exact_validated_weather_vector_only(monkeypatch):
    evaluation = {
        "passed": True,
        "domain": {
            "feature_version": FEATURE_VERSION,
            "soils": ["TEST-FIXTURE"],
            "planting_month_day": "11-15",
            "max_daily_depth_mm": 150,
            "feature_ranges": {
                "season_et0_mm": [400, 500],
                "irr_total_mm": [0, 600],
                "w11_net_mm": [0, 100],
                "w11_balance_mm": [-105, -60],
            },
            "validated_weather": {
                "known-sha": {"season_et0_mm": 550, "w11_p_mm": 0, "w11_et0_mm": 107}
            },
        },
    }
    monkeypatch.setattr(domain, "load_evaluation", lambda *args: evaluation)
    monkeypatch.setattr(
        domain.soils, "soil", lambda *args: SimpleNamespace(engine_soil_type="loam")
    )

    def check(weather="known-sha", **features):
        return domain.check(
            "wheat",
            "TEST-FIXTURE",
            {
                "season_et0_mm": 550,
                "irr_total_mm": 300,
                "w11_net_mm": 0,
                "w11_balance_mm": -107,
                "w11_p_mm": 0,
                "w11_et0_mm": 107,
                **features,
            },
            planting_month_day="11-15",
            max_daily_depth_mm=75,
            version="TEST-FIXTURE",
            weather_sha256=weather,
        )

    assert check().in_domain
    assert not check("unknown-sha").in_domain
    assert not check(season_et0_mm=560).in_domain
    assert not check(irr_total_mm=900).in_domain
    assert not check(w11_net_mm=150, w11_balance_mm=43).in_domain
    assert not check(w11_balance_mm=-500).in_domain
    evaluation["passed"] = False
    assert not check().in_domain
