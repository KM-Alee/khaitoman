"""Candidate policies and libraries (T5.5–T5.7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .base import PKR, NonNegFloat, Sha256, StrictModel
from .crop import IrrigationEvent
from .water import LedgerEvent


class ResourceUse(StrictModel):
    """Sparse consumption of one shared resource in one atomic interval."""

    resource_id: str  # "source", "edge:<id>", "pump:<id>", "gw:<asset>"
    interval_id: str
    volume_m3: NonNegFloat


class StateOutcome(StrictModel):
    state_id: str  # weather (and supply) state
    deliverable: bool
    crop_outcome_hash: Sha256 | None
    yield_kg_ha: NonNegFloat | None
    production_kg: NonNegFloat | None
    ledger_ref: str | None = None
    resources: list[ResourceUse] = Field(default_factory=list)
    service_credit_m3: NonNegFloat = 0.0
    groundwater_m3: NonNegFloat = 0.0
    canal_receipt_m3: NonNegFloat = 0.0
    validation_ref: str | None = None
    # Additions (science stream, backwards compatible):
    weather_scenario_id: str | None = None
    supply_profile_id: str | None = None
    violations: list[str] = Field(default_factory=list)  # why undeliverable
    pond_loss_m3: NonNegFloat = 0.0
    pond_spill_m3: NonNegFloat = 0.0
    pond_rain_m3: NonNegFloat = 0.0
    terminal_pond_m3: NonNegFloat = 0.0


class AtomicInterval(StrictModel):
    """Smallest non-overlapping delivery interval (T4.1)."""

    interval_id: str
    start: datetime
    end: datetime


class ResourceCapacity(StrictModel):
    """Upper bound of a shared resource in one interval; None ids = applies to all."""

    resource_id: str
    interval_id: str  # atomic interval, local day ("d2026-12-01") or "season"
    capacity_m3: NonNegFloat
    state_id: str | None = None
    shared_configuration_id: str | None = None


class CandidatePolicy(StrictModel):
    candidate_policy_id: str
    candidate_policy_hash: Sha256
    field_id: str
    crop_profile_id: str
    soil_profile_id: str
    shared_configuration_id: str
    required_instance_ids: list[str] = Field(default_factory=list)
    family: str  # e.g. "baseline_B0", "rainfed", "full_window", "pond_shift", "pump_topup"
    coverage_tags: list[str] = Field(default_factory=list)
    receipt_events: list[LedgerEvent] = Field(default_factory=list)
    application_schedule: list[IrrigationEvent] = Field(default_factory=list)
    pond_events: list[LedgerEvent] = Field(default_factory=list)
    pump_events: list[LedgerEvent] = Field(default_factory=list)
    application_efficiency: float
    cropped_area_ha: NonNegFloat
    seasonal_opex_pkr: PKR = 0
    outcomes: list[StateOutcome]
    generator_version: str
    # Additions (science stream, backwards compatible):
    resources: list[ResourceUse] = Field(default_factory=list)  # state-invariant use
    template_id: str | None = None
    uses_asset_ids: list[str] = Field(default_factory=list)  # existing assets operated
    receipt_volume_m3: NonNegFloat = 0.0
    pump_volume_m3: NonNegFloat = 0.0
    gross_application_mm: NonNegFloat = 0.0
    attributes: dict[str, Any] = Field(default_factory=dict)


class LibraryCoverage(StrictModel):
    field_id: str
    generated: int
    rejected: int
    retained: int
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    families: dict[str, int] = Field(default_factory=dict)


class SharedConfiguration(StrictModel):
    shared_configuration_id: str
    repair_instance_ids: list[str]
    capex_pkr: PKR
    seasonal_opex_pkr: PKR = 0
    edge_delivery_factors: dict[str, float]


class CandidateLibrary(StrictModel):
    candidate_library_hash: Sha256
    pilot_id: str
    pilot_version: str
    season_id: str
    state_ids: list[str]
    configurations: list[SharedConfiguration]
    policies_ref: str  # parquet/jsonl of CandidatePolicy
    coverage: list[LibraryCoverage]
    generator_version: str
    created_at: datetime
    # Additions (science stream, backwards compatible):
    intervals: list[AtomicInterval] = Field(default_factory=list)
    capacities: list[ResourceCapacity] = Field(default_factory=list)
    typical_state_id: str | None = None
    supply_profile_ids: list[str] = Field(default_factory=list)
    weather_scenario_ids: list[str] = Field(default_factory=list)
    decision_at: datetime | None = None
    excluded_instances: dict[str, str] = Field(default_factory=dict)  # instance -> reason
    build_stats: dict[str, Any] = Field(default_factory=dict)
