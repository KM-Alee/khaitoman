"""Crop profiles and season calendars (PRD §2.2, §5.4; T5.2).

Engine names were verified against the installed AquaCrop-OSPy 3.1.0
``crop_params`` table. Choices (inspected by running both variants on ERA5
weather at the Lower Chenab discovery point, 2022-23):

* Wheat -> ``WheatGDD``. Thermal-time phenology keeps development coherent when
  analog years are date-shifted; 15 Nov planting reaches maturity in early April,
  which matches the Punjab rabi calendar. The calendar-day ``Wheat`` profile
  (197 d to maturity) would run to the end of May.
* Cotton -> ``Cotton`` (calendar days, 174 d to maturity): 1 May planting
  matures late October as in Punjab kharif. ``CottonGDD`` (Tbase 12, Tupp 35)
  matured in mid-August with zero yield under Punjab heat, so it was rejected.

A profile's ``planting_date`` is the reference season's date; the engine uses
its month/day (AquaCrop takes ``mm/dd``) inside each experiment's window.
Parameters are package defaults (uncalibrated): yields are model output, not
local predictions.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from aabflow.domain.schemas import Crop, CropProfile, Season
from aabflow.science.paths import atomic_write_text, libraries_dir

# Declared field application limits passed explicitly as MaxIrr / MaxIrrSeason (T5.2).
# Punjab basin/flood turns apply ~50-100 mm; 150 mm/day is the physical upper
# limit of one basin application, not a recommendation.
WHEAT = CropProfile(
    crop_profile_id="wheat-punjab-gdd-v1",
    crop=Crop.wheat,
    engine_crop_name="WheatGDD",
    parameter_set_version="aquacrop-3.1.0-default-WheatGDD",
    planting_date=date(2026, 11, 15),
    earliest_planting=date(2026, 11, 1),
    latest_harvest=date(2027, 5, 31),
    yield_basis="dry_grain",
    calibration_status="uncalibrated",
    max_daily_irrigation_mm=150.0,
    max_season_irrigation_mm=1200.0,
    evidence_ids=["ev-science-crop-wheat-profile"],
)

COTTON = CropProfile(
    crop_profile_id="cotton-punjab-v1",
    crop=Crop.cotton,
    engine_crop_name="Cotton",
    parameter_set_version="aquacrop-3.1.0-default-Cotton",
    planting_date=date(2027, 5, 1),
    earliest_planting=date(2027, 4, 15),
    latest_harvest=date(2027, 12, 15),
    yield_basis="dry_seed_cotton_model",
    calibration_status="uncalibrated",
    max_daily_irrigation_mm=150.0,
    max_season_irrigation_mm=1600.0,
    evidence_ids=["ev-science-crop-cotton-profile"],
)

CROP_PROFILES: dict[str, CropProfile] = {p.crop_profile_id: p for p in (WHEAT, COTTON)}

# Days between simulation start and planting: initial soil state is declared at
# the simulation start, not ambiguously at planting (T5.3).
PRE_PLANT_DAYS = 14

DECISION_AT = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)  # 08:00 PKT, PRD §2.2 decision date


def profile(crop_profile_id: str) -> CropProfile:
    try:
        return CROP_PROFILES[crop_profile_id]
    except KeyError:
        raise KeyError(f"unknown crop profile {crop_profile_id!r}") from None


def season_crop(crop: Crop) -> CropProfile:
    """The release profile for a crop (one profile per crop/yield basis in v2)."""
    return next(p for p in CROP_PROFILES.values() if p.crop is crop)


def planting_in_window(p: CropProfile, sim_start: date) -> date:
    """First occurrence of the profile's month/day on or after ``sim_start``."""
    d = date(sim_start.year, p.planting_date.month, p.planting_date.day)
    if d < sim_start:
        d = date(sim_start.year + 1, p.planting_date.month, p.planting_date.day)
    return d


def season_window(p: CropProfile, planting: date) -> tuple[date, date]:
    """Simulation window: PRE_PLANT_DAYS before planting to the latest harvest."""
    start = planting - timedelta(days=PRE_PLANT_DAYS)
    lh = p.latest_harvest
    end = date(planting.year, lh.month, lh.day)
    if end <= planting:
        end = date(planting.year + 1, lh.month, lh.day)
    return start, end


def _season(
    season_id: str,
    p: CropProfile,
    planting: date,
    modes: list[str],
    basis: str,
    label: str,
    decision_at: datetime,
    notes: list[str],
) -> Season:
    start, end = season_window(p, planting)
    return Season(
        season_id=season_id,
        crop=p.crop,
        crop_profile_id=p.crop_profile_id,
        start=start,
        end=end,
        planning_modes=modes,
        planting_date=planting,
        sim_start=start,
        sim_end=end,
        decision_at=decision_at,
        weather_basis=basis,  # type: ignore[arg-type]
        label=label,
        notes=notes,
    )


SEASONS: dict[str, Season] = {
    s.season_id: s
    for s in [
        _season(
            "wheat-rabi-2026-27",
            WHEAT,
            date(2026, 11, 15),
            ["season_response"],
            "analog",
            "Rabi wheat 2026-27 (season response)",
            DECISION_AT,
            [
                "Scenario calendar until locally reviewed (PRD §2.2).",
                (
                    "Decision 10 Oct 2026: 90-day ponds and 120-day repairs cannot commission "
                    "before 15 Nov planting; availability follows commissioning dates."
                ),
            ],
        ),
        _season(
            "wheat-rabi-2027-28",
            WHEAT,
            date(2027, 11, 15),
            ["capital_planning"],
            "analog",
            "Rabi wheat 2027-28 (capital planning)",
            DECISION_AT,
            ["Future investment season leaving construction time (PRD §2.2)."],
        ),
        _season(
            "cotton-kharif-2027",
            COTTON,
            date(2027, 5, 1),
            ["season_response", "capital_planning"],
            "analog",
            "Kharif cotton 2027",
            DECISION_AT,
            [
                (
                    "Planting ~1 May 2027 leaves time to commission ponds and repairs "
                    "(PRD §2.2); new assets may legitimately appear."
                )
            ],
        ),
        _season(
            "wheat-rabi-2024-25",
            WHEAT,
            date(2024, 11, 15),
            ["historical_replay"],
            "actual",
            "Rabi wheat 2024-25 (historical replay)",
            datetime(2024, 10, 1, 3, 0, tzinfo=UTC),
            [
                "Retrospective replay under actual archived gridded weather; no forecast claim.",
                "Counterfactual proposed assets are dated from a 1 Oct 2024 decision.",
            ],
        ),
    ]
}


def season(season_id: str) -> Season:
    try:
        return SEASONS[season_id]
    except KeyError:
        raise KeyError(f"unknown season {season_id!r}") from None


def publish() -> None:
    """Write data/libraries/{seasons,crop_profiles}.json."""
    d = libraries_dir()
    atomic_write_text(
        d / "seasons.json",
        json.dumps([s.model_dump(mode="json") for s in SEASONS.values()], indent=2),
    )
    atomic_write_text(
        d / "crop_profiles.json",
        json.dumps([p.model_dump(mode="json") for p in CROP_PROFILES.values()], indent=2),
    )
