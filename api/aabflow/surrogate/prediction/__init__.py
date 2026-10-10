"""Surrogate preview and exact confirmation (T8.4, PRD §7.4).

``preview(policy_inputs)`` returns a typed ``SurrogatePreview`` with
``estimate_kind="surrogate_preview"``; out-of-domain input yields no estimate and
the message "Outside validated preview range—run crop model.". A preview never
replaces exact crop outputs: ``confirm(policy_inputs)`` builds the exact
``CropExperiment`` and runs it through ``run_experiment`` (cached by hash),
returning the ``CropOutcome`` and the preview-vs-exact difference.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

import pandas as pd
from pydantic import Field

from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import CropOutcome, IrrigationEvent, StrictModel, SurrogatePreview
from aabflow.science import crop_profiles, scenarios, soils
from aabflow.science.experiments import make_experiment, run_experiment
from aabflow.science.paths import models_dir
from aabflow.science.weather import load_weather
from aabflow.surrogate import domain as sdomain
from aabflow.surrogate.features import FEATURE_VERSION, compute_features, feature_names

OUT_OF_DOMAIN_MESSAGE = "Outside validated preview range—run crop model."


class PreviewRequest(StrictModel):
    crop_profile_id: str
    soil_profile_id: str
    application_efficiency: float = Field(ge=0, le=1)
    schedule: list[IrrigationEvent] = Field(default_factory=list)
    season_id: str
    weather_scenario_id: str = "typical"
    pilot_id: str | None = None
    weather_sha256: str | None = None  # overrides the scenario lookup (e.g. historical replay)
    candidate_policy_id: str | None = None
    physical_precheck_status: str = "not_run"
    physical_precheck_reasons: list[str] = Field(default_factory=list)


@lru_cache(maxsize=4)
def _booster(version: str, crop: str):
    import lightgbm as lgb

    return lgb.Booster(model_file=str(models_dir() / version / f"model-{crop}.txt"))


def _resolve(req: PreviewRequest) -> tuple[Any, Any, str, date, date]:
    cp = crop_profiles.profile(req.crop_profile_id)
    season = crop_profiles.season(req.season_id)
    if season.crop_profile_id != cp.crop_profile_id:
        raise ValueError(
            f"crop profile {cp.crop_profile_id} does not belong to season {req.season_id}"
        )
    sha = req.weather_sha256
    if sha is None:
        ws = {
            w.weather_scenario_id: w
            for w in scenarios.load_weather_scenarios(req.season_id, req.pilot_id)
        }
        if req.weather_scenario_id not in ws:
            raise KeyError(
                f"unknown weather scenario {req.weather_scenario_id} for {req.season_id}"
            )
        sha = ws[req.weather_scenario_id].transformed_sha256
    return cp, soils.soil(req.soil_profile_id), sha, season.sim_start, season.sim_end


def _sched(req: PreviewRequest) -> list[tuple[date, float]]:
    agg: dict[date, float] = {}
    for e in req.schedule:
        agg[e.date] = agg.get(e.date, 0.0) + e.gross_depth_mm
    return sorted(agg.items())


def preview(policy_inputs: PreviewRequest | dict[str, Any]) -> SurrogatePreview:
    req = (
        policy_inputs
        if isinstance(policy_inputs, PreviewRequest)
        else PreviewRequest.model_validate(policy_inputs)
    )
    version = sdomain.latest_version()
    cp, sp, sha, start, _end = _resolve(req)
    sched = _sched(req)
    feats = compute_features(cp, sp, req.application_efficiency, sched, load_weather(sha), start)
    max_depth = max((v for _, v in sched), default=0.0)
    dom = sdomain.check(
        cp.crop.value,
        sp.soil_profile_id,
        feats,
        planting_month_day=cp.planting_date.strftime("%m-%d"),
        max_daily_depth_mm=max_depth,
        version=version,
    )
    ev = sdomain.load_evaluation(version, cp.crop.value)
    phash = content_hash(
        req.model_dump(
            mode="json", exclude={"physical_precheck_status", "physical_precheck_reasons"}
        )
    )
    est = None
    if dom.in_domain:
        x = pd.DataFrame(
            [[feats[n] for n in feature_names(cp.crop)]], columns=feature_names(cp.crop)
        )
        est = max(0.0, float(_booster(version, cp.crop.value).predict(x)[0]))
    band = ev.get("residual_band_kg_ha")
    return SurrogatePreview(
        preview_id=f"pv_{content_hash([phash, version])[:24]}",
        proposed_policy_hash=phash,
        model_version=version,
        feature_version=FEATURE_VERSION,
        crop_profile_id=cp.crop_profile_id,
        estimated_yield_kg_ha=est,
        domain_status="in_domain" if dom.in_domain else "out_of_domain",
        domain_reasons=dom.reasons,
        evaluation_reference=f"data/models/{version}/evaluation-{cp.crop.value}.json",
        uncertainty_note=(
            "Approximate preview from a LightGBM model of executed AquaCrop runs; held-out test-year "
            f"nMAE {ev['test']['nmae']:.3f}. The residual band is an empirical held-out 5-95% range, "
            "not a calibrated confidence interval. Verify with the crop model before any final use."
        ),
        residual_band_kg_ha=(band[0], band[1]) if band and est is not None else None,
        physical_precheck_status=req.physical_precheck_status,  # type: ignore[arg-type]
        physical_precheck_reasons=req.physical_precheck_reasons,
        message=None if dom.in_domain else OUT_OF_DOMAIN_MESSAGE,
    )


def exact_experiment(policy_inputs: PreviewRequest | dict[str, Any]):
    req = (
        policy_inputs
        if isinstance(policy_inputs, PreviewRequest)
        else PreviewRequest.model_validate(policy_inputs)
    )
    cp, sp, sha, start, end = _resolve(req)
    return make_experiment(
        cp.crop_profile_id,
        sp.soil_profile_id,
        req.weather_scenario_id,
        sha,
        start,
        end,
        req.application_efficiency,
        _sched(req),
    )


def confirm(
    policy_inputs: PreviewRequest | dict[str, Any],
) -> tuple[CropOutcome, SurrogatePreview, float | None]:
    """Exact confirmation path: run_experiment + the preview it replaces (difference kg/ha)."""
    pv = preview(policy_inputs)
    outcome = run_experiment(exact_experiment(policy_inputs))
    diff = (
        None if pv.estimated_yield_kg_ha is None else pv.estimated_yield_kg_ha - outcome.yield_kg_ha
    )
    return outcome, pv, diff
