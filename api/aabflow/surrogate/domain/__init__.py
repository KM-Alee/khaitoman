"""Surrogate validated domain (T8.4): categories, feature ranges, schedule/date domain, versions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from aabflow.science import soils
from aabflow.science.paths import models_dir
from aabflow.surrogate.features import FEATURE_VERSION

RANGE_MARGIN = 0.02  # fraction of the trained range tolerated at each end


@dataclass
class DomainResult:
    in_domain: bool
    reasons: list[str] = field(default_factory=list)


def latest_version() -> str:
    p = models_dir() / "surrogate-latest.json"
    if not p.exists():
        raise FileNotFoundError("no trained surrogate (run scripts/science_train_surrogate.py)")
    return json.loads(p.read_text())["model_version"]


@lru_cache(maxsize=8)
def load_evaluation(version: str, crop: str) -> dict[str, Any]:
    return json.loads((models_dir() / version / f"evaluation-{crop}.json").read_text())


def check(
    crop: str,
    soil_profile_id: str,
    features: dict[str, float],
    *,
    planting_month_day: str,
    max_daily_depth_mm: float,
    feature_version: str = FEATURE_VERSION,
    version: str | None = None,
) -> DomainResult:
    version = version or latest_version()
    try:
        ev = load_evaluation(version, crop)
    except FileNotFoundError:
        return DomainResult(False, [f"no surrogate model for crop {crop!r}"])
    dom = ev["domain"]
    reasons: list[str] = []
    if not ev.get("passed"):
        reasons.append("surrogate evaluation gate not passed; previews disabled")
    if feature_version != dom["feature_version"]:
        reasons.append(f"stale feature version {feature_version} != {dom['feature_version']}")
    try:
        sp = soils.soil(soil_profile_id)
        trained = {soils.soil(s).engine_soil_type for s in dom["soils"]}
        if sp.engine_soil_type not in trained:
            reasons.append(
                f"soil class {sp.engine_soil_type} not in the training domain {sorted(trained)}"
            )
    except KeyError:
        reasons.append(f"unreviewed soil profile {soil_profile_id}")
    if planting_month_day != dom["planting_month_day"]:
        reasons.append(
            f"unsupported season mapping: planting {planting_month_day} vs {dom['planting_month_day']}"
        )
    if max_daily_depth_mm > dom["max_daily_depth_mm"]:
        reasons.append(
            f"extreme irrigation depth {max_daily_depth_mm} mm > {dom['max_daily_depth_mm']} mm"
        )
    for name, (lo, hi) in dom["feature_ranges"].items():
        v = features.get(name)
        if v is None:
            reasons.append(f"missing feature {name}")
            continue
        pad = (hi - lo) * RANGE_MARGIN
        if v < lo - pad - 1e-9 or v > hi + pad + 1e-9:
            reasons.append(f"{name}={v:.3g} outside trained range [{lo:.3g}, {hi:.3g}]")
    return DomainResult(not reasons, reasons)
