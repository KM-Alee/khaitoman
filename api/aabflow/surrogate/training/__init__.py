"""Surrogate design, exact simulation batch, whole-year splits, training and evaluation (T8.1-T8.3).

Design per crop: every complete historical season of the science weather series
(original dates) x 3 soil archetypes x 2 application efficiencies x 12 dated
schedules drawn from 10 policy families (deterministic RNG per context). Each
schedule resolves to actual dated depths and is executed exactly through
``run_batch`` (cached by experiment hash, restart safe).

Split manifest (fixed before any fitting): the most recent complete season shared
by every weather source is the untouched test year; earlier years form the development pool evaluated
with leave-one-year-out CV; the ``irregular`` family is held out from fitting
and evaluated separately. Models: one LightGBM regressor per crop/yield basis,
explicit thread count. Baseline: training-only linear regression.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aabflow.config import DATA_DIR
from aabflow.domain.hashes import content_hash, file_sha256
from aabflow.domain.schemas import Crop
from aabflow.science import crop_profiles, scenarios, soils
from aabflow.science.adapter import ADAPTER_VERSION
from aabflow.science.experiments import crop_experiment_hash, make_experiment, run_batch
from aabflow.science.paths import atomic_write_text, models_dir
from aabflow.science.weather import load_weather, slice_window, store_weather
from aabflow.surrogate.features import (
    FEATURE_VERSION,
    compute_features,
    feature_names,
    linear_component_prediction,
    weather_feature_names,
)
from aabflow.surrogate.validation import (
    GATES,
    decision_regret,
    gate,
    regression_metrics,
    within_context_spearman,
)

TRAINING_DEVICE = os.environ.get("AABFLOW_SURROGATE_DEVICE", "cpu")
if TRAINING_DEVICE not in ("cpu", "gpu"):
    raise ValueError("AABFLOW_SURROGATE_DEVICE must be cpu or gpu")
MODEL_VERSION = "surrogate-v7-gpu" if TRAINING_DEVICE == "gpu" else "surrogate-v7"
RELEASE_DESIGN_SEED = "release-audit-v7"
LINEAR_FEATURES = [
    "irr_total_mm",
    "app_eff",
    "init_pct_taw",
    "soil_taw_mm_m",
    "season_p_mm",
    "season_et0_mm",
]
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
    device_type=TRAINING_DEVICE,
    gpu_use_dp=True,
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
    source: str = "science-discovery"
    calendar_season_id: str | None = None


def build_design(crop: Crop, pilot_id: str | None = None) -> list[DesignRow]:
    season = next(
        s for s in crop_profiles.SEASONS.values() if s.crop is crop and s.weather_basis == "analog"
    )
    src = scenarios.weather_source(pilot_id)
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
                        DesignRow(
                            crop,
                            label,
                            planting,
                            soil,
                            eff,
                            fam,
                            sched,
                            sha,
                            start,
                            end,
                            pilot_id or "science-discovery",
                        )
                    )
    return rows


def build_calendar_design(crop: Crop, pilot_id: str) -> list[DesignRow]:
    """Execute published analogs on their target calendars, keeping source-year splits.

    Mapping a non-leap historical season onto a leap-year planning season adds
    a weather day. Historical-date designs alone therefore do not cover every
    published feature window. Group each mapped experiment with its ORIGINAL
    weather year, so copies of held-out weather never enter the training pool.
    """
    rows = []
    for season in crop_profiles.SEASONS.values():
        if season.crop is not crop:
            continue
        for weather in scenarios.load_weather_scenarios(season.season_id, pilot_id):
            year = weather.analog_season_start.year
            label = f"{year}-{str(year + 1)[-2:]}" if crop is Crop.wheat else str(year)
            for soil in SOILS:
                for eff in EFFS:
                    rng = np.random.default_rng(
                        int(content_hash([crop.value, year, soil, eff])[:8], 16)
                    )
                    for family, schedule in design_schedules(crop, season.planting_date, rng):
                        rows.append(
                            DesignRow(
                                crop,
                                label,
                                season.planting_date,
                                soil,
                                eff,
                                family,
                                schedule,
                                weather.transformed_sha256,
                                season.sim_start,
                                season.sim_end,
                                pilot_id,
                                season.season_id,
                            )
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
            else:
                raise RuntimeError(f"surrogate crop experiment {h} failed: {rep.failed.get(h)}")
        pending = nxt
        if not pending:
            break
    if pending:
        raise RuntimeError("surrogate schedules still fail after crop-termination adjustment")
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
                "weather_source": r.source,
                "weather_sha256": r.weather_sha,
                "calendar_season_id": r.calendar_season_id,
                "soil": r.soil,
                "app_eff": r.eff,
                "family": r.family,
                "yield_kg_ha": y,
                **f,
            }
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- training / evaluation


class ResidualRegressor:
    """Training-only linear trend plus a nonlinear LightGBM residual model."""

    def __init__(self, trend, residual):
        self.trend = trend
        self.residual = residual
        self.booster_ = residual.booster_

    def predict(self, X):
        return (
            self.trend.predict(X[LINEAR_FEATURES]) if self.trend is not None else 0
        ) + self.residual.predict(X)


def _fit(X: pd.DataFrame, y: np.ndarray, *, residual=True):
    import lightgbm as lgb
    from sklearn.linear_model import LinearRegression

    trend = LinearRegression().fit(X[LINEAR_FEATURES], y) if residual else None
    m = lgb.LGBMRegressor(**LGB_PARAMS)
    m.fit(X, y - trend.predict(X[LINEAR_FEATURES]) if trend is not None else y)
    return ResidualRegressor(trend, m)


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
    by_source = {str(source): set(group["year"]) for source, group in df.groupby("weather_source")}
    common = set.intersection(*by_source.values())
    if len(common) < 2:
        raise ValueError(
            "training requires development and untouched test years shared by every source"
        )
    test_year = max(common)
    return {
        "rule": "latest complete year shared by all sources = untouched test year; "
        "earlier years = LOYO development pool; newer source-only years excluded from fitting; "
        f"family '{HOLDOUT_FAMILY}' held out from fitting",
        "test_year": test_year,
        "development_years": [year for year in years if year < test_year],
        "excluded_newer_years": [year for year in years if year > test_year],
        "test_weather_sources": sorted(by_source),
        "holdout_family": HOLDOUT_FAMILY,
        "fixed_before_fitting": True,
        "crop": crop.value,
        "test_schedule_design_seed": RELEASE_DESIGN_SEED,
        "test_weather_note": "Weather years match prior release checks; this release uses newly executed schedules, never fitted. No parameters are selected from final-year or held-out-family results.",
    }


def train_and_evaluate(df: pd.DataFrame, crop: Crop) -> tuple[Any, dict[str, Any]]:
    feats = feature_names(crop)
    man = split_manifest(df, crop)
    dev = df[df["year"].isin(man["development_years"])]
    fit_pool = dev[dev["family"] != HOLDOUT_FAMILY]
    reference = float(fit_pool["yield_kg_ha"].median())
    # leave-one-year-out CV over development years
    candidates = {"direct": [], "residual": []}
    for yr in man["development_years"]:
        tr = fit_pool[fit_pool["year"] != yr]
        va = dev[(dev["year"] == yr) & (dev["family"] != HOLDOUT_FAMILY)]
        for architecture, folds in candidates.items():
            m = _fit(tr[feats], tr["yield_kg_ha"].to_numpy(), residual=architecture == "residual")
            pred = np.clip(m.predict(va[feats]), 0, None)
            met = regression_metrics(va["yield_kg_ha"].to_numpy(), pred, reference)
            folds.append({"year": yr, **met})
    scores = {
        name: float(np.mean([f["nmae"] for f in folds])) for name, folds in candidates.items()
    }
    architecture = min(scores, key=lambda name: (scores[name], name))
    comparison = {
        "candidates": scores,
        "selected": architecture,
        "selection_basis": "Development-year LOYO mean nMAE only; selection frozen before final-year predictions",
    }
    folds = candidates[architecture]
    final = _fit(
        fit_pool[feats], fit_pool["yield_kg_ha"].to_numpy(), residual=architecture == "residual"
    )
    # Cross-fitted development residuals estimate the model's additive bias.
    # The correction has no threshold or test-dependent parameter choice.
    correction = -float(
        np.average([fold["bias_kg_ha"] for fold in folds], weights=[fold["n"] for fold in folds])
    )
    test = df[df["year"] == man["test_year"]].copy()
    test["pred"] = np.clip(final.predict(test[feats]) + correction, 0, None)
    test["baseline"] = _baseline(fit_pool[feats], fit_pool["yield_kg_ha"].to_numpy(), test[feats])
    test_main = test[test["family"] != HOLDOUT_FAMILY]
    test_hold = test[test["family"] == HOLDOUT_FAMILY]
    hold_dev = dev[dev["family"] == HOLDOUT_FAMILY]
    hold_pred = np.clip(final.predict(hold_dev[feats]) + correction, 0, None)
    resid = (test_main["pred"] - test_main["yield_kg_ha"]).to_numpy()
    metrics: dict[str, Any] = {
        "crop": crop.value,
        "model_version": MODEL_VERSION,
        "training_device": TRAINING_DEVICE,
        "linear_component": {
            "features": LINEAR_FEATURES,
            "coefficients": final.trend.coef_.tolist(),
            "intercept": float(final.trend.intercept_),
            "basis": "Fitted to development years and non-held-out schedule families only; LightGBM predicts the residual.",
        }
        if final.trend is not None
        else None,
        "architecture_development_comparison": comparison,
        "prediction_bias_correction_kg_ha": correction,
        "bias_correction_basis": "Negative sample-weighted mean prediction bias from development-year LOYO folds only; excludes test year and held-out schedule family.",
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
        "test_ranking": within_context_spearman(
            test_main, "pred", ["weather_source", "soil", "app_eff"]
        ),
        "baseline_test": regression_metrics(
            test_main["yield_kg_ha"].to_numpy(), test_main["baseline"].to_numpy(), reference
        ),
        "decision_regret": [
            {**f, "weather_source": source, "fixture_id": f"{source}:{f['fixture_id']}"}
            for source, g in test_main.groupby("weather_source")
            for f in decision_regret(g, "pred")
        ],
        "residual_band_kg_ha": [float(np.quantile(resid, 0.05)), float(np.quantile(resid, 0.95))],
        "pilot_note": "Discovery and published pilot weather are pooled. Mapped planning calendars "
        "retain original weather-year split assignments; metrics measure simulated yield, not field calibration.",
        "gates": GATES,
    }
    # Each pilot has the same untouched weather year. Report every holdout type
    # independently so pooled scores cannot conceal one pilot's errors.
    hold_dev = hold_dev.copy()
    hold_dev["pred"] = hold_pred
    metrics["test_by_source"] = {}
    for source in man["test_weather_sources"]:
        source_test = test[test["weather_source"] == source]
        main = source_test[source_test["family"] != HOLDOUT_FAMILY]
        family = source_test[source_test["family"] == HOLDOUT_FAMILY]
        family_dev = hold_dev[hold_dev["weather_source"] == source]
        entry = {
            "year": man["test_year"],
            "test": regression_metrics(
                main["yield_kg_ha"].to_numpy(), main["pred"].to_numpy(), reference
            ),
            "test_ranking": within_context_spearman(main, "pred", ["soil", "app_eff"]),
            "test_by_soil": {
                soil: regression_metrics(
                    g["yield_kg_ha"].to_numpy(), g["pred"].to_numpy(), reference
                )
                for soil, g in main.groupby("soil")
            },
            "test_holdout_family": regression_metrics(
                family["yield_kg_ha"].to_numpy(), family["pred"].to_numpy(), reference
            ),
            "dev_holdout_family": regression_metrics(
                family_dev["yield_kg_ha"].to_numpy(), family_dev["pred"].to_numpy(), reference
            ),
            "baseline_test": regression_metrics(
                main["yield_kg_ha"].to_numpy(), main["baseline"].to_numpy(), reference
            ),
            "decision_regret": [
                f for f in metrics["decision_regret"] if f["weather_source"] == source
            ],
        }
        entry["gate_results"] = gate(entry)
        metrics["test_by_source"][source] = entry
    reg = [f["regret"] for f in metrics["decision_regret"]]
    metrics["decision_regret_summary"] = {
        "n": len(reg),
        "median": float(np.median(reg)),
        "max": float(np.max(reg)),
        "median_kg": float(np.median([f["regret_kg"] for f in metrics["decision_regret"]])),
    }
    metrics["gate_results"] = gate(metrics)
    metrics["gate_results"]["all_weather_sources"] = all(
        all(entry["gate_results"].values()) for entry in metrics["test_by_source"].values()
    )
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
    # Release validation covers untouched published weather as well as fitting
    # weather. Pin weather-only feature vectors by input hash; never widen the
    # fitted irrigation/soil ranges or borrow held-out outcomes for fitting.
    metrics["domain"]["validated_weather"] = {
        str(sha): {name: float(group.iloc[0][name]) for name in weather_feature_names(crop)}
        for sha, group in test.groupby("weather_sha256")
        if all(
            all(metrics["test_by_source"][str(source)]["gate_results"].values())
            for source in group["weather_source"].unique()
        )
    }
    metrics["domain"]["validated_weather_basis"] = (
        "Exact weather input hashes evaluated in the untouched test-year release check; model fitting excludes that year. Soil and irrigation ranges remain fitting-only."
    )
    return final, metrics


def refresh_release_design(rows: list[DesignRow], crop: Crop, test_year: str) -> None:
    """Deterministic new test schedules; development rows and year assignments stay fixed."""
    from collections import defaultdict

    counts = defaultdict(int)
    for row in rows:
        if row.year_label != test_year:
            continue
        rng = np.random.default_rng(
            int(
                content_hash([RELEASE_DESIGN_SEED, crop.value, row.year_label, row.soil, row.eff])[
                    :8
                ],
                16,
            )
        )
        matching = [
            schedule
            for family, schedule in design_schedules(crop, row.planting, rng)
            if family == row.family
        ]
        key = (
            row.source,
            row.weather_sha,
            row.soil,
            row.eff,
            row.planting,
            row.calendar_season_id,
            row.family,
        )
        # Two regular/weekly-turn variants per context; duplicate published
        # weather contexts reuse identical designs and exact experiment hashes.
        row.schedule = matching[counts[key] % len(matching)]
        counts[key] += 1


def train_all(workers: int | None = None, crops=(Crop.wheat, Crop.cotton)) -> dict[str, Any]:
    t0 = time.perf_counter()
    out_dir = models_dir() / MODEL_VERSION
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "training_device": TRAINING_DEVICE,
        "created_at": datetime.now(UTC).isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "crops": {},
    }
    pilots = training_pilots()
    summary["weather_sources"] = ["science-discovery", *pilots]
    for crop in crops:
        # Pool the discovery archive with every published pilot's own series so the trained
        # domain covers the weather scenarios the pilots actually use (T8.2 domain checks).
        rows = build_design(crop)
        for pid in pilots:
            rows += build_design(crop, pid)
            rows += build_calendar_design(crop, pid)
        # Freeze an independent final schedule design before any fitting or
        # release-year crop execution. Source-year assignments remain unchanged.
        row_manifest = split_manifest(
            pd.DataFrame(
                {"year": [r.year_label for r in rows], "weather_source": [r.source for r in rows]}
            ),
            crop,
        )
        refresh_release_design(rows, crop, row_manifest["test_year"])
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
    if summary["passed"]:
        atomic_write_text(
            models_dir() / "surrogate-latest.json", json.dumps({"model_version": MODEL_VERSION})
        )
    return summary


def training_pilots() -> list[str]:
    """Published pilots whose package weather joins the training pool."""
    idx = DATA_DIR / "pilots" / "index.json"
    if not idx.exists():
        return []
    return sorted({p["pilot_id"] for p in json.loads(idx.read_text())})


def model_dir(version: str | None = None) -> Path:
    from aabflow.surrogate.domain import latest_version

    return models_dir() / (version or latest_version())


def external_evaluation(
    pilot_id: str, workers: int | None = None, version: str | None = None
) -> dict[str, Any]:
    """Evaluate a pilot on the model's untouched whole-year release split, without refitting.

    Pilot archives may also be in the fitting pool. Restrict to the stored test
    year so development-year predictions cannot be presented as untouched.
    """
    import lightgbm as lgb

    from aabflow.surrogate.domain import latest_version

    version = version or latest_version()

    out: dict[str, Any] = {
        "model_version": version,
        "pilot_id": pilot_id,
        "created_at": datetime.now(UTC).isoformat(),
        "crops": {},
    }
    src = scenarios.weather_source(pilot_id)
    out["weather_origin"] = src.origin
    out["series_id"] = src.series_id
    for crop in (Crop.wheat, Crop.cotton):
        ev = json.loads((models_dir() / version / f"evaluation-{crop.value}.json").read_text())
        test_year = ev["split_manifest"]["test_year"]
        rows = [row for row in build_design(crop, pilot_id) if row.year_label == test_year]
        if not rows:
            raise ValueError(f"{pilot_id} has no untouched {crop.value} test year {test_year}")
        df = execute_design(rows, workers=workers)
        feats = feature_names(crop)
        booster = lgb.Booster(model_file=str(models_dir() / version / f"model-{crop.value}.txt"))
        df["pred"] = np.clip(
            booster.predict(df[feats])
            + linear_component_prediction(df, ev)
            + ev.get("prediction_bias_correction_kg_ha", 0.0),
            0,
            None,
        )
        ref = ev["test"]["reference_yield_kg_ha"]
        last = max(df["year"].unique())
        last_df = df[(df["year"] == last) & (df["family"] != HOLDOUT_FAMILY)]
        regret = decision_regret(last_df, "pred")
        rv = [f["regret"] for f in regret]
        out["crops"][crop.value] = {
            "samples": len(df),
            "years": sorted(df["year"].unique().tolist()),
            "all": regression_metrics(df["yield_kg_ha"].to_numpy(), df["pred"].to_numpy(), ref),
            "ranking": within_context_spearman(df, "pred", ["year", "soil", "app_eff"]),
            "decision_regret_year": last,
            "decision_regret": {
                "n": len(rv),
                "median": float(np.median(rv)),
                "max": float(np.max(rv)),
            },
        }
        df.to_parquet(
            models_dir() / version / f"external-{pilot_id}-{crop.value}.parquet", index=False
        )
    atomic_write_text(
        models_dir() / version / f"external-{pilot_id}.json", json.dumps(out, indent=1, default=str)
    )
    return out
