"""Runs, solver outcomes and jobs (T6.6, T9.2, T9.4)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field

from .base import CONTRACT_VERSION, PlanKind, SolverStatus, StrictModel
from .water import PhysicalValidationReport


class ConfigurationStatus(StrictModel):
    shared_configuration_id: str
    status: SolverStatus
    objective_value: float | None
    upper_bound: float | None
    wall_ms: int


class _RunBase(StrictModel):
    contract_version: Literal["2.0.0"] = CONTRACT_VERSION
    run_id: str
    scenario_revision_id: str
    scenario_hash: str
    candidate_library_hash: str
    plan_kind: PlanKind
    proof_scope: Literal["finite_candidate_library"] = "finite_candidate_library"
    primary_objective: str
    solve_wall_ms: int
    configurations: list[ConfigurationStatus] = Field(default_factory=list)
    candidate_coverage_ref: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class PlanRun(_RunBase):
    """A feasible, reconstructed and validated plan."""

    outcome: Literal["plan"] = "plan"
    solver_status: Literal[SolverStatus.OPTIMAL, SolverStatus.FEASIBLE]
    objective_value: float
    objective_upper_bound: float | None
    relative_gap: float | None
    selected_candidate_policy_ids: list[str]
    selected_intervention_instance_ids: list[str]
    shared_configuration_id: str
    metric_refs: list[str]
    physical_validation: PhysicalValidationReport
    trajectory_bundle_ref: str
    comparison_compatibility_key: str


class InfeasibilityKind(StrEnum):
    missing_input = "missing_input"
    empty_option_set = "empty_option_set"
    finite_candidate_incompatibility = "finite_candidate_incompatibility"
    bound_contradiction = "bound_contradiction"


class NoPlanRun(_RunBase):
    """INFEASIBLE / UNKNOWN / MODEL_INVALID: diagnostics only, never plan metrics."""

    outcome: Literal["no_plan"] = "no_plan"
    solver_status: Literal[
        SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN, SolverStatus.MODEL_INVALID
    ]
    infeasibility_kind: InfeasibilityKind | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class InvalidPlanRun(_RunBase):
    """Solver found an incumbent but original-precision reconstruction failed (INVALID_PLAN)."""

    outcome: Literal["invalid_plan"] = "invalid_plan"
    solver_status: SolverStatus
    physical_validation: PhysicalValidationReport
    diagnostic_ref: str


RunResult = Annotated[PlanRun | NoPlanRun | InvalidPlanRun, Field(discriminator="outcome")]


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    waiting_for_review = "waiting_for_review"
    succeeded = "succeeded"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"
    interrupted = "interrupted"


class Job(StrictModel):
    job_id: str
    operation: str
    request_hash: str
    state: JobState
    progress: float | None = None  # from completed subjobs only
    stage: str | None = None
    result_ref: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class JobEvent(StrictModel):
    event_id: int
    job_id: str
    created_at: datetime
    type: Literal["stage", "progress", "heartbeat", "result", "error", "cancelled"]
    payload: dict[str, Any] = Field(default_factory=dict)
