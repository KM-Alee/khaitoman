"""Shared Pydantic base and enumerations for the v2 contract (T3, T9).

All public models reject unknown fields and nonfinite numbers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "2.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


class FrozenModel(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


NonNegFloat = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
DeliveryFactor = Annotated[float, Field(gt=0, le=1)]
PKR = Annotated[int, Field(ge=0, description="Integer Pakistani rupees")]
DecimalRate = Annotated[str, Field(pattern=r"^\d+(\.\d+)?$", description="Decimal string rate")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Crop(StrEnum):
    wheat = "wheat"
    cotton = "cotton"


class PlanningMode(StrEnum):
    historical_replay = "historical_replay"
    season_response = "season_response"
    capital_planning = "capital_planning"


class OptimizationMode(StrEnum):
    typical = "typical"
    worst_case = "worst_case"


class Objective(StrEnum):
    production_kg = "production_kg"
    irrigation_contribution_pkr = "irrigation_contribution_pkr"


class PlanKind(StrEnum):
    """Baseline ladder (PRD §6.4)."""

    B0 = "B0"  # fixed-roster policy
    B1 = "B1"  # optimized, no new capital
    P = "P"  # integrated portfolio
    R = "R"  # robust across uncertainty set


class ActionCategory(StrEnum):
    """Five action categories (PRD §6.2)."""

    timing = "timing"  # timing with available assets
    leveling = "leveling"
    pond = "pond"
    shared_repair = "shared_repair"
    pump_supplement = "pump_supplement"


class SolverStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"


class ErrorCode(StrEnum):
    """Domain error codes (T9.3)."""

    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    ASSET_UNAVAILABLE = "ASSET_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MODEL_INVALID = "MODEL_INVALID"
    INVALID_PLAN = "INVALID_PLAN"
    CANDIDATE_COVERAGE_LIMITED = "CANDIDATE_COVERAGE_LIMITED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class ApiError(StrictModel):
    code: ErrorCode
    detail: str
    fields: dict[str, str] = Field(default_factory=dict)
