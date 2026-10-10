"""Analog selection rule, supply profiles and the 9-state uncertainty set (PRD §5.4, §7.3). TEST FIXTURE weather."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from aabflow.science import crop_profiles, scenarios
from aabflow.water.roster import resolve_supply


def synthetic_source(rain_by_year: dict[int, float]) -> scenarios.WeatherSource:
    d = pd.date_range("2005-01-01", "2026-06-30", freq="D")
    rain = np.array([rain_by_year.get(x.year if x.month >= 7 else x.year - 1, 0.0) for x in d])
    df = pd.DataFrame(
        {
            "Date": d.astype("datetime64[ns]"),
            "MinTemp": 8.0,
            "MaxTemp": 24.0,
            "Precipitation": rain,
            "ReferenceET": 3.0,
        }
    )
    return scenarios.WeatherSource(
        "fixture", df, (30.8, 72.5), (30.75, 72.5), "30.7500,72.5000", "TEST FIXTURE", {}
    )


def test_tercile_median_rule_and_pool_precedes_decision():
    years = list(range(2005, 2026))
    rain = {y: 0.1 * (i + 1) for i, y in enumerate(years)}  # wetter every year
    s = crop_profiles.season("wheat-rabi-2026-27")
    pick, ranked = scenarios.select_analogs(s, synthetic_source(rain))
    n = len(ranked)
    k = n // 3
    assert n >= scenarios.MIN_POOL
    assert pick["dry"].isoformat() == ranked[(k - 1) // 2]["planting"]
    assert pick["typical"].isoformat() == ranked[(n - 1) // 2]["planting"]
    assert pick["wet"].isoformat() == ranked[n - k + (k - 1) // 2]["planting"]
    assert pick["dry"] < pick["typical"] < pick["wet"]  # monotone rain by year in this fixture
    decision = date(2026, 10, 10)
    assert all(
        crop_profiles.season_window(crop_profiles.WHEAT, date.fromisoformat(r["planting"]))[1]
        < decision
        for r in ranked
    )
    assert {"hot_days_late", "max_10day_precip_mm", "precip_share_m12"} <= set(ranked[0])


def test_replay_pool_excludes_the_replayed_season_and_later():
    s = crop_profiles.season("wheat-rabi-2024-25")
    _, ranked = scenarios.select_analogs(
        s, synthetic_source({y: 1.0 + y % 3 for y in range(2005, 2026)})
    )
    assert all(date.fromisoformat(r["planting"]) < date(2024, 1, 1) for r in ranked)


def test_too_short_archive_rejected():
    src = synthetic_source({})
    src = scenarios.WeatherSource(
        "x",
        src.frame[src.frame.Date >= "2019-01-01"],
        src.point_requested,
        src.point_returned,
        src.grid_cell,
        src.origin,
        {},
    )
    with pytest.raises(scenarios.ScenarioError, match="complete historical seasons"):
        scenarios.select_analogs(crop_profiles.season("wheat-rabi-2026-27"), src)


def test_supply_profiles_and_nine_states():
    s = crop_profiles.season("cotton-kharif-2027")
    profs = scenarios.supply_profiles(s, "a" * 64)
    assert [p.supply_profile_id for p in profs] == list(scenarios.SUPPLY_IDS)
    res = {p.supply_profile_id: resolve_supply(p) for p in profs}
    assert res["shortage-22pct-v1"].multiplier == pytest.approx(0.78)
    closure = res["interruption-14d-v1"].closures[0]
    assert (closure.end - closure.start).days == 14 and not closure.edge_ids  # whole source
    assert len({p.resolved_hash for p in profs}) == 3
    us = scenarios.uncertainty_set("pilot-a", s, profs)
    assert len(us.states) == 9 and len({x.state_id for x in us.states}) == 9
    assert {x.weather_scenario_id for x in us.states} == {"dry", "typical", "wet"}
