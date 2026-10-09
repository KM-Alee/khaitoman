"""Provenance and metric values (T3.3)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .base import StrictModel


class EvidenceKind(StrEnum):
    observed_remote_sensing = "observed_remote_sensing"
    public_geography = "public_geography"
    gridded_reanalysis = "gridded_reanalysis"
    literature = "literature"
    user_supplied = "user_supplied"
    assumption = "assumption"
    model_output = "model_output"
    derived = "derived"


class VerificationState(StrEnum):
    unchecked = "unchecked"
    source_checked = "source_checked"
    artifact_checked = "artifact_checked"
    locally_reviewed = "locally_reviewed"


class AssumptionRange(StrictModel):
    low: float
    high: float
    unit: str


class EvidenceRecord(StrictModel):
    evidence_id: str
    source_title: str
    kind: EvidenceKind
    verification_state: VerificationState = VerificationState.unchecked
    source_url: str | None = None
    source_asset_id: str | None = None
    retrieved_at: datetime | None = None
    source_period: str | None = None
    geographic_scope: str | None = None
    license_id: str | None = None
    raw_sha256: str | None = None
    transformation: str | None = None
    parent_evidence_ids: list[str] = Field(default_factory=list)
    units: str | None = None
    method_version: str | None = None
    limitations: list[str] = Field(default_factory=list)
    assumption_range: AssumptionRange | None = None
    allowed_use: str | None = None
    reviewer: str | None = None
    reviewed_at: datetime | None = None


class MetricStatus(StrEnum):
    available = "available"
    not_estimated = "not_estimated"
    not_applicable = "not_applicable"
    blocked = "blocked"


class MetricValue(StrictModel):
    """Every displayed KPI is one of these, from the server metric registry (T7.5)."""

    metric_id: str
    definition_id: str
    run_id: str
    value: float | None
    unit: str
    status: MetricStatus
    reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    crop: str | None = None
    field_id: str | None = None
