"""Scenario requests and immutable revisions (T3.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from .base import (
    CONTRACT_VERSION,
    PKR,
    Fraction,
    Objective,
    OptimizationMode,
    PlanKind,
    PlanningMode,
    Sha256,
    StrictModel,
)


class ScenarioRequest(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    pilot_id: str
    pilot_version: str
    season_id: str
    planning_mode: PlanningMode
    decision_at: datetime
    weather_scenario_ids: list[str] = Field(min_length=1)
    supply_profile_id: str
    uniform_reduction_fraction: Fraction = 0.0
    capital_budget_pkr: PKR
    operating_budget_pkr: PKR
    objective: Objective = Objective.production_kg
    optimization_mode: OptimizationMode = OptimizationMode.typical
    uncertainty_set_id: str | None = None
    minimum_service_ratio: Fraction | None = None
    service_group: Literal["all", "head", "middle", "tail"] | None = None
    permit_groundwater: bool = True
    blocked_edge_ids: list[str] = Field(default_factory=list)
    allowed_intervention_instance_ids: list[str] | None = None  # None = all eligible
    forced_instance_ids: list[str] = Field(default_factory=list)
    excluded_instance_ids: list[str] = Field(default_factory=list)
    assumption_set_id: str = "declared-assumptions-v1"

    @model_validator(mode="after")
    def _check(self) -> ScenarioRequest:
        if self.decision_at.tzinfo is None:
            raise ValueError("decision_at must include a UTC offset")
        if self.optimization_mode is OptimizationMode.worst_case:
            if not self.uncertainty_set_id:
                raise ValueError("worst_case requires uncertainty_set_id")
            if self.objective is not Objective.production_kg:
                raise ValueError("worst_case supports the production_kg objective only")
        if (self.minimum_service_ratio is None) != (self.service_group is None):
            raise ValueError("minimum_service_ratio and service_group go together")
        if set(self.forced_instance_ids) & set(self.excluded_instance_ids):
            raise ValueError("an instance cannot be both forced and excluded")
        return self


class ScenarioRevision(StrictModel):
    scenario_revision_id: str
    scenario_id: str
    parent_revision_id: str | None
    request: ScenarioRequest
    semantic_hash: Sha256
    candidate_library_hash: Sha256 | None
    created_at: datetime


class RevisionChange(StrictModel):
    """Typed changes for derived revisions (also the copilot's branch_scenario surface, T11.3)."""

    capital_budget_pkr: PKR | None = None
    operating_budget_pkr: PKR | None = None
    supply_profile_id: str | None = None
    uniform_reduction_fraction: Fraction | None = None
    weather_scenario_ids: list[str] | None = None
    minimum_service_ratio: Fraction | None = None
    service_group: Literal["all", "head", "middle", "tail"] | None = None
    allowed_intervention_instance_ids: list[str] | None = None
    forced_instance_ids: list[str] | None = None
    excluded_instance_ids: list[str] | None = None
    permit_groundwater: bool | None = None
    blocked_edge_ids: list[str] | None = None
    optimization_mode: OptimizationMode | None = None
    uncertainty_set_id: str | None = None


class SolveRequest(StrictModel):
    plan_kind: PlanKind = PlanKind.P
    time_limit_s: float = Field(default=10.0, gt=0, le=120)
