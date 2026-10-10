"""The trained surrogate domain covers the UI's default preview request on every published scenario.

Default request (Explore > Surrogate): siltloam, application efficiency 0.6 and four 75 mm
irrigations from planting. Before the pilot-weather retrain this was out of domain for every
wheat season because the pilots' series run hotter/drier than the discovery archive.
"""

from datetime import timedelta

import pytest

from aabflow.science import crop_profiles, scenarios
from aabflow.surrogate.prediction import preview

PILOTS = sorted({p for p, _ in scenarios.published_pilots()})
CASES = [
    (pid, sid, w.weather_scenario_id)
    for pid in PILOTS
    for sid in crop_profiles.SEASONS
    for w in scenarios.load_weather_scenarios(sid, pid)
]


def default_request(pilot_id: str, season_id: str, scenario_id: str, offsets=(0, 21, 42, 63)):
    season = crop_profiles.SEASONS[season_id]
    return {
        "crop_profile_id": season.crop_profile_id,
        "soil_profile_id": "aquacrop-siltloam-pct50",
        "application_efficiency": 0.6,
        "season_id": season_id,
        "weather_scenario_id": scenario_id,
        "pilot_id": pilot_id,
        "schedule": [
            {"date": (season.planting_date + timedelta(days=d)).isoformat(), "gross_depth_mm": 75.0}
            for d in offsets
        ],
    }


def test_cases_cover_both_pilots():
    assert {"pilot-a", "pilot-b"} <= set(PILOTS)
    assert len(CASES) >= 26


@pytest.mark.parametrize("pilot_id,season_id,scenario_id", CASES)
@pytest.mark.parametrize("offsets", [(0, 21, 42, 63), (10, 31, 52, 73)])
def test_default_preview_in_domain(pilot_id, season_id, scenario_id, offsets):
    pv = preview(default_request(pilot_id, season_id, scenario_id, offsets))
    assert pv.domain_status == "in_domain", pv.domain_reasons
    assert pv.estimated_yield_kg_ha and pv.estimated_yield_kg_ha > 0
