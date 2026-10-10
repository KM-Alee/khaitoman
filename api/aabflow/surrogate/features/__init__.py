"""Surrogate features (T8.2): experiment inputs only, never simulated outcomes.

Features: soil hydraulic constants of the AquaCrop class and the declared
initial moisture, application efficiency, planting-relative schedule
summaries (gross and net-of-efficiency depth per fixed growth-calendar window,
event count/timing, longest gap) and weather summaries over the same windows
(P, ET0, Tmax, Tmin, P + net irrigation - ET0). Harvest index, biomass, stress
or any engine output are excluded (target leakage).
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from aabflow.domain.schemas import Crop, CropProfile, SoilProfile
from aabflow.science import crop_profiles, soils

FEATURE_VERSION = "surrogate-features-v2"
# Fortnight inputs preserve timing differences that a monthly mean hides.
N_WINDOWS = 14
WINDOW_DAYS = {Crop.wheat: 14, Crop.cotton: 14}
HOT_C = {Crop.wheat: 35.0, Crop.cotton: 45.0}


@lru_cache(maxsize=32)
def soil_constants(engine_soil_type: str) -> dict[str, float]:
    from aquacrop.entities.soil import Soil

    s = Soil(engine_soil_type)
    prof = s.profile
    return {
        "soil_th_fc": float(prof["th_fc"].mean()),
        "soil_th_wp": float(prof["th_wp"].mean()),
        "soil_th_s": float(prof["th_s"].mean()),
        "soil_ksat": float(prof["Ksat"].mean()),
    }


def initial_pct(sp: SoilProfile) -> float:
    kind, val = soils.parse_initial_water(sp.initial_water)
    if kind == "Pct":
        return float(val[0])
    return {"FC": 100.0, "WP": 0.0, "SAT": 120.0}[str(val[0])]


def feature_names(crop: Crop) -> list[str]:
    names = [
        "app_eff",
        "init_pct_taw",
        "soil_th_fc",
        "soil_th_wp",
        "soil_th_s",
        "soil_ksat",
        "soil_taw_mm_m",
        "irr_total_mm",
        "irr_events",
        "irr_max_mm",
        "irr_first_dap",
        "irr_last_dap",
        "irr_mean_dap",
        "irr_max_gap_d",
        "preplant_p_mm",
        "preplant_et0_mm",
        "season_p_mm",
        "season_et0_mm",
        "season_balance_mm",
        "hot_days_late",
    ]
    for k in range(N_WINDOWS):
        names += [
            f"w{k}_irr_mm",
            f"w{k}_net_mm",
            f"w{k}_p_mm",
            f"w{k}_et0_mm",
            f"w{k}_tmax",
            f"w{k}_tmin",
            f"w{k}_rain_days",
            f"w{k}_heat_days",
            f"w{k}_balance_mm",
        ]
    return names


def weather_feature_names(crop: Crop) -> list[str]:
    """Weather-only inputs, independent of irrigation and soil; no fitted transform."""
    return [
        name
        for name in feature_names(crop)
        if name
        in {"preplant_p_mm", "preplant_et0_mm", "season_p_mm", "season_et0_mm", "hot_days_late"}
        or any(
            name == f"w{k}_{suffix}"
            for k in range(N_WINDOWS)
            for suffix in ("p_mm", "et0_mm", "tmax", "tmin", "rain_days", "heat_days")
        )
    ]


def linear_component_prediction(frame: pd.DataFrame, evaluation: dict) -> np.ndarray:
    component = evaluation.get("linear_component")
    if component is None:
        return np.zeros(len(frame))
    return (
        frame[component["features"]].to_numpy() @ np.asarray(component["coefficients"])
        + component["intercept"]
    )


def compute_features(
    crop: CropProfile,
    soil: SoilProfile,
    application_efficiency: float,
    schedule: Sequence[tuple[date, float]],
    weather: pd.DataFrame,
    sim_start: date,
) -> dict[str, float]:
    planting = crop_profiles.planting_in_window(crop, sim_start)
    wl = WINDOW_DAYS[crop.crop]
    sc = soil_constants(soil.engine_soil_type)
    w = weather.copy()
    w["Date"] = pd.to_datetime(w["Date"])
    dap = (w["Date"] - pd.Timestamp(planting)).dt.days.to_numpy()
    p = w["Precipitation"].to_numpy(dtype=float)
    et0 = w["ReferenceET"].to_numpy(dtype=float)
    tmax = w["MaxTemp"].to_numpy(dtype=float)
    tmin = w["MinTemp"].to_numpy(dtype=float)
    agg: dict[int, float] = {}
    for d, mm in schedule:
        if mm > 0:
            k = (d - planting).days
            agg[k] = agg.get(k, 0.0) + float(mm)
    days = sorted(agg)
    depths = np.array([agg[k] for k in days], dtype=float)
    total = float(depths.sum())
    f: dict[str, float] = {
        "app_eff": float(application_efficiency),
        "init_pct_taw": initial_pct(soil),
        **sc,
        "soil_taw_mm_m": (sc["soil_th_fc"] - sc["soil_th_wp"]) * 1000.0,
        "irr_total_mm": total,
        "irr_events": float(len(days)),
        "irr_max_mm": float(depths.max()) if len(days) else 0.0,
        "irr_first_dap": float(days[0]) if days else -1.0,
        "irr_last_dap": float(days[-1]) if days else -1.0,
        "irr_mean_dap": float((np.array(days) * depths).sum() / total) if total > 0 else -1.0,
    }
    horizon = wl * N_WINDOWS
    marks = [0] + [k for k in days if 0 <= k <= horizon] + [horizon]
    f["irr_max_gap_d"] = float(max(b - a for a, b in itertools.pairwise(marks)))
    pre = dap < 0
    f["preplant_p_mm"] = float(p[pre].sum())
    f["preplant_et0_mm"] = float(et0[pre].sum())
    seas = (dap >= 0) & (dap < horizon)
    f["season_p_mm"] = float(p[seas].sum())
    f["season_et0_mm"] = float(et0[seas].sum())
    irr_net_total = total * application_efficiency
    f["season_balance_mm"] = f["season_p_mm"] + irr_net_total - f["season_et0_mm"]
    late = (dap >= 3 * wl) & (dap < horizon)
    f["hot_days_late"] = float((tmax[late] >= HOT_C[crop.crop]).sum())
    for k in range(N_WINDOWS):
        m = (dap >= k * wl) & (dap < (k + 1) * wl)
        if k == N_WINDOWS - 1:
            m = dap >= k * wl
        irr = sum(
            v
            for d, v in agg.items()
            if (k * wl <= d < (k + 1) * wl) or (k == N_WINDOWS - 1 and d >= k * wl)
        )
        f[f"w{k}_irr_mm"] = float(irr)
        f[f"w{k}_net_mm"] = float(irr * application_efficiency)
        f[f"w{k}_p_mm"] = float(p[m].sum())
        f[f"w{k}_et0_mm"] = float(et0[m].sum())
        f[f"w{k}_tmax"] = float(tmax[m].mean()) if m.any() else 0.0
        f[f"w{k}_tmin"] = float(tmin[m].mean()) if m.any() else 0.0
        f[f"w{k}_rain_days"] = float((p[m] >= 1.0).sum())
        f[f"w{k}_heat_days"] = float((tmax[m] >= HOT_C[crop.crop]).sum())
        f[f"w{k}_balance_mm"] = f[f"w{k}_p_mm"] + f[f"w{k}_net_mm"] - f[f"w{k}_et0_mm"]
    _ = timedelta  # planting-relative arithmetic only
    return {n: f[n] for n in feature_names(crop.crop)}
