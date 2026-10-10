"""Surrogate preview contract (T8.4). Added by the science stream (backwards compatible)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import NonNegFloat, StrictModel


class SurrogatePreview(StrictModel):
    preview_id: str
    proposed_policy_hash: str
    model_version: str
    feature_version: str
    crop_profile_id: str
    estimated_yield_kg_ha: NonNegFloat | None  # None when out of domain
    estimate_kind: Literal["surrogate_preview"] = "surrogate_preview"
    domain_status: Literal["in_domain", "out_of_domain"]
    domain_reasons: list[str] = Field(default_factory=list)
    evaluation_reference: str  # path of the evaluation report backing this model
    uncertainty_note: str
    residual_band_kg_ha: tuple[float, float] | None = None  # empirical held-out band, not a CI
    physical_precheck_status: Literal["passed", "failed", "not_run"] = "not_run"
    physical_precheck_reasons: list[str] = Field(default_factory=list)
    exact_confirmation_job_id: str | None = None
    message: str | None = None  # e.g. "Outside validated preview range—run crop model."
