"""Surrogate design, exact simulation batch, whole-year splits, training and evaluation (T8.1-T8.3).

Design per crop: every complete historical season of the science weather series
(original dates) x 3 soil archetypes x 2 application efficiencies x 12 dated
schedules drawn from 10 policy families (deterministic RNG per context). Each
schedule resolves to actual dated depths and is executed exactly through
``run_batch`` (cached by experiment hash, restart safe).

Split manifest (fixed before any fitting): the most recent complete season is
the untouched test year; all other years form the development pool evaluated
with leave-one-year-out CV; the ``irregular`` family is held out from fitting
and evaluated separately. Models: one LightGBM regressor per crop/yield basis,
explicit thread count. Baseline: training-only linear regression.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.schemas import Crop
from aabflow.science import crop_profiles, scenarios, soils
from aabflow.science.adapter import ADAPTER_VERSION
from aabflow.science.experiments import crop_experiment_hash, make_experiment, run_batch
from aabflow.science.paths import atomic_write_text, models_dir
from aabflow.science.weather import load_weather, slice_window, store_weather
from aabflow.surrogate.features import FEATURE_VERSION, compute_features, feature_names
from aabflow.surrogate.validation import (
    GATES,
    decision_regret,
    gate,
    regression_metrics,
    within_context_spearman,
)

MODEL_VERSION = "surrogate-v1"
SOILS = ["aquacrop-siltloam-pct50", "aquacrop-loam-pct50", "aquacrop-sandyloam-pct50"]
EFFS = [0.6, 0.75]
FAMILIES = [
    "rainfed",
    "regular",
    "front_loaded",
    "back_loaded",
    "critical",
    "deficit_frequent",
    "weekly_turn",
    "skip_phase",
    "heavy_few",
    "irregular",
]
HOLDOUT_FAMILY = "irregular"
STOP_DAP = {Crop.wheat: 115, Crop.cotton: 150}
CRITICAL = {Crop.wheat: [25, 55, 75, 95, 105], Crop.cotton: [30, 60, 80, 100, 120]}
LGB_PARAMS = dict(  # noqa: C408 - keyword form mirrors the LightGBM API
    n_estimators=800,
    learning_rate=0.03,
    num_leaves=31,
    min_child_samples=8,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    num_threads=4,
    verbose=-1,
    random_state=0,
)


def _sched(planting: date, pairs) -> list[tuple[date, float]]:
    agg: dict[date, float] = {}
    for dap, mm in pairs:
        if mm > 0:
            d = planting + timedelta(days=int(dap))
            agg[d] = agg.get(d, 0.0) + round(float(mm), 1)
    return sorted((d, min(v, 150.0)) for d, v in agg.items())


def design_schedules(
    crop: Crop, planting: date, rng: np.random.Generator
) -> list[tuple[str, list]]:
    stop = STOP_DAP[crop]
    out: list[tuple[str, list]] = [("rainfed", [])]
    iv = int(rng.choice([7, 10, 14, 21]))
    d = float(rng.uniform(30, 80))
    s0 = int(rng.integers(0, 25))
    out.append(("regular", _sched(planting, [(k, d) for k in range(s0, stop, iv)])))
    n = int(rng.integers(4, 8))
    daps = np.linspace(int(rng.integers(0, 15)), stop, n)
    out.append(
        (
            "front_loaded",
            _sched(planting, [(k, 100 - 70 * i / (n - 1)) for i, k in enumerate(daps)]),
        )
    )
    out.append(
        ("back_loaded", _sched(planting, [(k, 30 + 70 * i / (n - 1)) for i, k in enumerate(daps)]))
    )
    crit = rng.choice(CRITICAL[crop], size=int(rng.integers(2, 5)), replace=False)
    out.append(("critical", _sched(planting, [(k, rng.uniform(50, 100)) for k in sorted(crit)])))
    out.append(
        (
            "deficit_frequent",
            _sched(planting, [(k, rng.uniform(10, 25)) for k in range(5, stop, 7)]),
        )
    )
    turn = float(rng.uniform(15, 45))
    out.append(
        (
            "weekly_turn",
            _sched(planting, [(k, turn) for k in range(int(rng.integers(0, 7)), stop, 7)]),
        )
    )
    skip = int(rng.integers(0, 4)) * 30
    out.append(
        (
            "skip_phase",
            _sched(planting, [(k, d) for k in range(s0, stop, iv) if not skip <= k < skip + 30]),
        )
    )
    out.append(
        (
            "heavy_few",
            _sched(
                planting,
                [
                    (k, rng.uniform(100, 150))
                    for k in sorted(rng.choice(range(10, stop), 3, replace=False))
                ],
            ),
        )
    )
    m = int(rng.integers(3, 12))
    out.append(
        (
            "irregular",
            _sched(
                planting,
                [
                    (int(k), rng.uniform(10, 120))
                    for k in sorted(rng.choice(range(stop), m, replace=False))
                ],
            ),
        )
    )
    out.append(
        (
            "regular",
            _sched(
                planting,
                [
                    (k, float(rng.uniform(20, 70)))
                    for k in range(int(rng.integers(0, 20)), stop, int(rng.choice([7, 14])))
                ],
            ),
        )
    )
    out.append(
        (
            "weekly_turn",
            _sched(planting, [(k, float(rng.uniform(10, 30))) for k in range(3, stop, 7)]),
        )
    )
    return out


@dataclass
class DesignRow:
    crop: Crop
    year_label: str
    planting: date
    soil: str
    eff: float
    family: str
    schedule: list
    weather_sha: str
    sim_start: date
    sim_end: date


def build_design(crop: Crop) -> list[DesignRow]:
    season = next(
        s for s in crop_profiles.SEASONS.values() if s.crop is crop and s.weather_basis == "analog"
    )
    src = scenarios.weather_source(None)
    cp = crop_profiles.profile(season.crop_profile_id)
    # historical pool: every complete season in the archive (original dates)
    rows: list[DesignRow] = []
    first, last = src.frame["Date"].min().date(), src.frame["Date"].max().date()
    for y in range(first.year - 1, last.year + 1):
        planting = date(y, cp.planting_date.month, cp.planting_date.day)
        start, end = crop_profiles.season_window(cp, planting)
        if start < first or end > last:
            continue
        sha, _ = store_weather(slice_window(src.frame, start, end))
        label = f"{y}-{str(y + 1)[-2:]}" if crop is Crop.wheat else str(y)
        for soil in SOILS:
            for eff in EFFS:
                rng = np.random.default_rng(int(content_hash([crop.value, y, soil, eff])[:8], 16))
                for fam, sched in design_schedules(crop, planting, rng):
                    rows.append(
                        DesignRow(crop, label, planting, soil, eff, fam, sched, sha, start, end)
                    )
    return rows


def _experiment(r: DesignRow):
    return make_experiment(
        crop_profiles.season_crop(r.crop).crop_profile_id,
        r.soil,
        f"hist-{r.year_label}",
        r.weather_sha,
        r.sim_start,
        r.sim_end,
        r.eff,
        r.schedule,
    )


def execute_design(rows: list[DesignRow], workers: int | None = None) -> pd.DataFrame:
    """Run (or reuse) every design experiment; truncate schedules after early crop termination once."""
    recs = []
    pending = rows
    for _round in range(3):
        exps = {}
        keyed = []
        for r in pending:
            e = _experiment(r)
            h = crop_experiment_hash(e)
            exps[h] = e
            keyed.append((r, h))
        rep = run_batch(exps.values(), workers=workers, progress=True)
        nxt = []
        for r, h in keyed:
            if h in rep.outcomes:
                o = rep.outcomes[h]
                recs.append((r, h, o.yield_kg_ha))
            elif "after crop termination" in (rep.failed.get(h) or ""):
                last = date.fromisoformat(rep.failed[h].rsplit("termination ", 1)[1][:10])
                r2 = DesignRow(
                    **{**r.__dict__, "schedule": [(d, v) for d, v in r.schedule if d < last]}
                )
                nxt.append(r2)
        pending = nxt
        if not pending:
            break
    weather_cache: dict[str, pd.DataFrame] = {}
    out = []
    for r, h, y in recs:
        if r.weather_sha not in weather_cache:
            weather_cache[r.weather_sha] = load_weather(r.weather_sha)
        cp = crop_profiles.season_crop(r.crop)
        f = compute_features(
            cp, soils.soil(r.soil), r.eff, r.schedule, weather_cache[r.weather_sha], r.sim_start
        )
        out.append(
            {
                "experiment_hash": h,
                "year": r.year_label,
                "soil": r.soil,
                "app_eff": r.eff,
                "family": r.family,
                "yield_kg_ha": y,
                **f,
            }
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- training / evaluation


def _fit(X: pd.DataFrame, y: np.ndarray):
    import lightgbm as lgb

    m = lgb.LGBMRegressor(**LGB_PARAMS)
    m.fit(X, y)
    return m


def _baseline(Xtr: pd.DataFrame, ytr: np.ndarray, Xte: pd.DataFrame) -> np.ndarray:
    from sklearn.linear_model import LinearRegression

    cols = [
        "irr_total_mm",
        "app_eff",
        "init_pct_taw",
        "soil_taw_mm_m",
        "season_p_mm",
        "season_et0_mm",
    ]
    lr = LinearRegression().fit(Xtr[cols], ytr)
    return np.clip(lr.predict(Xte[cols]), 0, None)


def split_manifest(df: pd.DataFrame, crop: Crop) -> dict[str, Any]:
    years = sorted(df["year"].unique())
    return {
        "rule": "most recent complete season = untouched test year; others = LOYO development pool; "
        f"family '{HOLDOUT_FAMILY}' held out from fitting",
        "test_year": years[-1],
        "development_years": years[:-1],
        "holdout_family": HOLDOUT_FAMILY,
        "fixed_before_fitting": True,
        "crop": crop.value,
    }


def train_and_evaluate(df: pd.DataFrame, crop: Crop) -> tuple[Any, dict[str, Any]]:
    feats = feature_names(crop)
    man = split_manifest(df, crop)
    dev = df[df["year"].isin(man["development_years"])]
    fit_pool = dev[dev["family"] != HOLDOUT_FAMILY]
    reference = float(fit_pool["yield_kg_ha"].median())
    # leave-one-year-out CV over development years
    folds = []
    for yr in man["development_years"]:
        tr = fit_pool[fit_pool["year"] != yr]
        va = dev[(dev["year"] == yr) & (dev["family"] != HOLDOUT_FAMILY)]
        m = _fit(tr[feats], tr["yield_kg_ha"].to_numpy())
        pred = np.clip(m.predict(va[feats]), 0, None)
        met = regression_metrics(va["yield_kg_ha"].to_numpy(), pred, reference)
        folds.append({"year": yr, **met})
    final = _fit(fit_pool[feats], fit_pool["yield_kg_ha"].to_numpy())
    test = df[df["year"] == man["test_year"]].copy()
    test["pred"] = np.clip(final.predict(test[feats]), 0, None)
    test["baseline"] = _baseline(fit_pool[feats], fit_pool["yield_kg_ha"].to_numpy(), test[feats])
    test_main = test[test["family"] != HOLDOUT_FAMILY]
    test_hold = test[test["family"] == HOLDOUT_FAMILY]
    hold_dev = dev[dev["family"] == HOLDOUT_FAMILY]
    hold_pred = np.clip(final.predict(hold_dev[feats]), 0, None)
    resid = (test_main["pred"] - test_main["yield_kg_ha"]).to_numpy()
    metrics: dict[str, Any] = {
        "crop": crop.value,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "samples": {
            "total": len(df),
            "fit_pool": len(fit_pool),
            "test": len(test_main),
            "holdout_family_test": len(test_hold),
            "years": int(df["year"].nunique()),
        },
        "split_manifest": man,
        "loyo_cv": {
            "folds": folds,
            "nmae_mean": float(np.mean([f["nmae"] for f in folds])),
            "nmae_max": float(np.max([f["nmae"] for f in folds])),
            "nmae_std": float(np.std([f["nmae"] for f in folds])),
        },
        "test": regression_metrics(
            test_main["yield_kg_ha"].to_numpy(), test_main["pred"].to_numpy(), reference
        ),
        "test_by_soil": {
            s: regression_metrics(g["yield_kg_ha"].to_numpy(), g["pred"].to_numpy(), reference)
            for s, g in test_main.groupby("soil")
        },
        "test_holdout_family": regression_metrics(
            test_hold["yield_kg_ha"].to_numpy(), test_hold["pred"].to_numpy(), reference
        )
        if len(test_hold)
        else None,
        "dev_holdout_family": regression_metrics(
            hold_dev["yield_kg_ha"].to_numpy(), hold_pred, reference
        )
        if len(hold_dev)
        else None,
        "test_ranking": within_context_spearman(test_main, "pred", ["soil", "app_eff"]),
        "baseline_test": regression_metrics(
            test_main["yield_kg_ha"].to_numpy(), test_main["baseline"].to_numpy(), reference
        ),
        "decision_regret": decision_regret(test_main, "pred"),
        "residual_band_kg_ha": [float(np.quantile(resid, 0.05)), float(np.quantile(resid, 0.95))],
        "pilot_note": "Weather is one ERA5 grid point (discovery series); pilot-level metrics equal the grid-cell "
        "metrics while pilots share that cell.",
        "gates": GATES,
    }
    reg = [f["regret"] for f in metrics["decision_regret"]]
    metrics["decision_regret_summary"] = {
        "n": len(reg),
        "median": float(np.median(reg)),
        "max": float(np.max(reg)),
        "median_kg": float(np.median([f["regret_kg"] for f in metrics["decision_regret"]])),
    }
    metrics["gate_results"] = gate(metrics)
    metrics["passed"] = all(metrics["gate_results"].values())
    # domain: categories, ranges, schedule/date domain
    metrics["domain"] = {
        "crop_profile_id": crop_profiles.season_crop(crop).crop_profile_id,
        "soils": sorted(df["soil"].unique()),
        "app_eff": [min(EFFS), max(EFFS)],
        "feature_ranges": {f: [float(fit_pool[f].min()), float(fit_pool[f].max())] for f in feats},
        "max_daily_depth_mm": 150.0,
        "planting_month_day": crop_profiles.season_crop(crop).planting_date.strftime("%m-%d"),
        "feature_version": FEATURE_VERSION,
    }
    return final, metrics


def train_all(workers: int | None = None, crops=(Crop.wheat, Crop.cotton)) -> dict[str, Any]:
    t0 = time.perf_counter()
    out_dir = models_dir() / MODEL_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "crops": {},
    }
    for crop in crops:
        rows = build_design(crop)
        df = execute_design(rows, workers=workers)
        data_path = out_dir / f"training-{crop.value}.parquet"
        df.to_parquet(data_path, index=False)
        model, metrics = train_and_evaluate(df, crop)
        mpath = out_dir / f"model-{crop.value}.txt"
        model.booster_.save_model(str(mpath))
        metrics["artifacts"] = {
            "model": mpath.name,
            "model_sha256": file_sha256(mpath),
            "training_data": data_path.name,
            "training_data_sha256": file_sha256(data_path),
            "design_rows": len(rows),
            "executed_rows": len(df),
        }
        atomic_write_text(
            out_dir / f"evaluation-{crop.value}.json", json.dumps(metrics, indent=1, default=str)
        )
        summary["crops"][crop.value] = {
            k: metrics[k]
            for k in (
                "test",
                "test_ranking",
                "decision_regret_summary",
                "baseline_test",
                "gate_results",
                "passed",
                "loyo_cv",
                "samples",
            )
        }
        summary["crops"][crop.value]["loyo_cv"] = {
            k: v for k, v in metrics["loyo_cv"].items() if k != "folds"
        }
    summary["passed"] = all(c["passed"] for c in summary["crops"].values())
    summary["wall_s"] = round(time.perf_counter() - t0, 1)
    atomic_write_text(out_dir / "evaluation.json", json.dumps(summary, indent=1, default=str))
    atomic_write_text(
        models_dir() / "surrogate-latest.json", json.dumps({"model_version": MODEL_VERSION})
    )
    return summary


def model_dir(version: str = MODEL_VERSION) -> Path:
    return models_dir() / version
