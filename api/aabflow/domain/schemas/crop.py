"""Crop, soil, weather, experiments and outcomes (T2.5, T5.2–T5.3)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .base import Crop, Fraction, NonNegFloat, Sha256, StrictModel


class CropProfile(StrictModel):
    crop_profile_id: str
    crop: Crop
    engine_crop_name: str  # verified AquaCrop name, e.g. "Wheat", "Cotton"
    parameter_set_version: str
    planting_date: date
    earliest_planting: date
    latest_harvest: date  # simulation window must cover maturity
    yield_basis: Literal["dry_grain", "dry_seed_cotton_model"]
    calibration_status: Literal["uncalibrated", "plausibility_checked", "calibrated"] = (
        "uncalibrated"
    )
    parameter_overrides: dict[str, float] = Field(default_factory=dict)
    max_daily_irrigation_mm: NonNegFloat  # passed as MaxIrr
    max_season_irrigation_mm: NonNegFloat  # passed as MaxIrrSeason
    evidence_ids: list[str] = Field(default_factory=list)


class SoilProfile(StrictModel):
    soil_profile_id: str
    engine_soil_type: str  # AquaCrop predefined class, e.g. "SiltLoam"
    archetype: str
    initial_water: Literal["FC", "WP", "SAT"] | str = "FC"
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class WeatherSeries(StrictModel):
    weather_series_id: str
    point_requested: tuple[float, float]  # lat, lon
    point_returned: tuple[float, float]
    elevation_m: float | None = None
    start: date
    end: date
    source: str = "open-meteo-archive"
    source_model: str | None = None
    raw_ref: str
    normalized_ref: str  # parquet: Date, MinTemp, MaxTemp, Precipitation, ReferenceET
    source_sha256: Sha256
    normalized_sha256: Sha256
    evidence_id: str


class WeatherScenario(StrictModel):
    """A named weather state for a season, mapped from an analog historical year."""

    weather_scenario_id: str  # e.g. "dry", "typical", "wet" or "hist-2022"
    season_id: str
    label: str
    analog_season_start: date
    weather_series_id: str
    date_mapping_ref: str | None = None  # original_date -> scenario_date table
    transformed_sha256: Sha256
    is_typical: bool = False
    selection_basis: str  # e.g. "seasonal precipitation tercile over 2015-2024"
    # Additions (science stream, backwards compatible):
    analog_season_label: str | None = None  # e.g. "2015-16"
    original_start: date | None = None
    original_end: date | None = None
    scenario_start: date | None = None
    scenario_end: date | None = None
    offset_days: int | None = None
    leap_rule: str | None = None
    leap_note: str | None = None
    source_sha256: Sha256 | None = None  # untransformed source window
    grid_cell: str | None = None  # returned archive grid point "lat,lon"
    statistics: dict[str, float] = Field(default_factory=dict)  # P, ET0, P-ET0, heat days...
    kind: Literal["analog", "actual"] = "analog"


class Season(StrictModel):
    season_id: str  # e.g. "wheat-rabi-2026-27"
    crop: Crop
    crop_profile_id: str
    start: date
    end: date
    planning_modes: list[str]
    # Additions (science stream, backwards compatible):
    planting_date: date | None = None
    sim_start: date | None = None  # crop simulation window; must cover maturity
    sim_end: date | None = None
    decision_at: datetime | None = None  # declared decision instant used for commissioning
    weather_basis: Literal["analog", "actual"] | None = None
    label: str | None = None
    notes: list[str] = Field(default_factory=list)


class IrrigationEvent(StrictModel):
    date: date  # local Asia/Karachi crop date
    gross_depth_mm: NonNegFloat


class CropExperiment(StrictModel):
    """Everything the crop engine sees. Area-independent (T5.6)."""

    crop_profile_id: str
    soil_profile_id: str
    weather_scenario_id: str
    weather_sha256: Sha256
    sim_start: date
    sim_end: date
    application_efficiency: Fraction
    schedule: list[IrrigationEvent]
    engine_name: str = "aquacrop-ospy"
    engine_version: str = "3.1.0"
    adapter_version: str


class CropOutcome(StrictModel):
    experiment_hash: Sha256
    engine_name: str
    engine_version: str
    adapter_version: str
    executed_at: datetime
    crop_profile_id: str
    soil_profile_id: str
    weather_sha256: Sha256
    schedule_hash: Sha256
    planting_date: date
    actual_harvest_date: date | None
    has_finished: bool
    yield_basis: str
    yield_kg_ha: NonNegFloat
    seasonal_irrigation_mm: NonNegFloat
    raw_output_refs: list[str]
    trajectory_ref: str  # parquet of daily series (canopy, biomass, soil water, ET, ...)
    field_mapping_version: str
    warnings: list[str] = Field(default_factory=list)
    evidence_id: str
