"""Supply profiles, uncertainty sets and the chronological ledger (T3.5, T4)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import Fraction, NonNegFloat, Sha256, StrictModel


class SupplyTransformation(StrictModel):
    transformation_id: str
    kind: Literal["absolute_multiplier", "relative_multiplier", "closure"]
    multiplier: Fraction | None = None
    start: datetime | None = None
    end: datetime | None = None
    edge_ids: list[str] = Field(default_factory=list)  # empty = whole source


class SupplyProfile(StrictModel):
    supply_profile_id: str
    base_profile_hash: Sha256
    label: str
    transformations: list[SupplyTransformation] = Field(default_factory=list)
    resolved_hash: Sha256
    pre_reduced: bool = False


class UncertaintyState(StrictModel):
    state_id: str
    weather_scenario_id: str
    supply_profile_id: str
    resolved_supply_profile_hash: Sha256


class UncertaintySet(StrictModel):
    uncertainty_set_id: str
    pilot_id: str
    season_id: str
    states: list[UncertaintyState]  # release grid: 3 weather x 3 supply = 9


class LedgerEventKind(StrEnum):
    source_release = "source_release"
    edge_transfer = "edge_transfer"
    edge_loss = "edge_loss"
    outlet_receipt = "outlet_receipt"
    field_application = "field_application"
    pond_fill = "pond_fill"
    pond_release = "pond_release"
    pond_evaporation = "pond_evaporation"
    pond_seepage = "pond_seepage"
    pond_rain = "pond_rain"
    pond_spill = "pond_spill"
    pump_abstraction = "pump_abstraction"
    unused_window = "unused_window"


class LedgerEvent(StrictModel):
    event_id: str
    timestamp: datetime  # UTC instant
    explicit_order: int = 0
    kind: LedgerEventKind
    volume_m3: NonNegFloat
    field_id: str | None = None
    asset_id: str | None = None
    edge_id: str | None = None
    window_id: str | None = None
    note: str | None = None


class RuleResidual(StrictModel):
    rule: str  # e.g. "pond_capacity", "edge_capacity", "node_balance", "receipt_right"
    passed: bool
    max_violation: float = 0.0
    unit: str = "m3"
    entity_ids: list[str] = Field(default_factory=list)
    at: datetime | None = None
    detail: str | None = None


class PhysicalValidationReport(StrictModel):
    status: Literal["passed", "failed", "not_run"]
    abs_tolerance_m3: NonNegFloat = 1e-6
    rel_tolerance: NonNegFloat = 1e-9
    residuals: list[RuleResidual] = Field(default_factory=list)
