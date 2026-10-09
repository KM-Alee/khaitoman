"""Candidate policies and libraries (T5.5–T5.7)."""

from __future__ import annotations

from datetime import datetime

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
