"""Exact crop experiments keyed by ``crop_experiment_hash`` (T3.6, T5.6).

``run_experiment(exp)`` returns a cached ``CropOutcome`` when
``data/experiments/<hash>/outcome.json`` exists, otherwise it runs the adapter
and publishes the artifact directory atomically:

    outcome.json, evidence.json, experiment.json,
    raw_simulation_results.parquet, raw_water_flux.parquet,
    raw_water_storage.parquet, raw_crop_growth.parquet, trajectory.parquet

The hash covers every actual model input: the experiment record, the fully
resolved crop and soil profile content, the daily weather content hash, and the
engine/adapter versions. Field area is excluded because the crop calculation is
per hectare (area-dependent effects change inputs, e.g. AppEff).

``run_batch`` evaluates many experiments in a process pool; each worker warms
numba up once in its initializer (T5.2) and skips completed hashes (restart safe).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import CropExperiment, CropOutcome, CropProfile, SoilProfile
from aabflow.science import crop_profiles, soils
from aabflow.science.adapter import (
    ADAPTER_VERSION,
    ENGINE_NAME,
    FIELD_MAPPING_VERSION,
    CropAdapterError,
    CropSimulatorAdapter,
    engine_version,
    schedule_frame,
)
from aabflow.science.paths import experiments_dir
from aabflow.science.weather import load_weather


def _resolved(exp: CropExperiment) -> tuple[CropProfile, SoilProfile]:
    return crop_profiles.profile(exp.crop_profile_id), soils.soil(exp.soil_profile_id)


def schedule_hash(exp: CropExperiment) -> str:
    sched = schedule_frame(exp)
    return content_hash(
        [
            [d.strftime("%Y-%m-%d"), float(v)]
            for d, v in zip(sched["Date"], sched["Depth"], strict=True)
        ]
    )


def crop_experiment_hash(
    exp: CropExperiment, crop: CropProfile | None = None, soil: SoilProfile | None = None
) -> str:
    cp, sp = (crop, soil) if crop and soil else _resolved(exp)
    body = exp.model_dump(mode="json")
    # Hash the aggregated daily schedule (event split within a day is not a model input).
    body["schedule"] = [
        [d.strftime("%Y-%m-%d"), float(v)]
        for d, v in zip(schedule_frame(exp)["Date"], schedule_frame(exp)["Depth"], strict=True)
    ]
    body["weather_scenario_id"] = None  # label only; the content hash identifies the weather
    return content_hash(
        {
            "experiment": body,
            "crop_profile": cp.model_dump(mode="json", exclude={"evidence_ids"}),
            "soil_profile": sp.model_dump(mode="json", exclude={"evidence_ids", "limitations"}),
            "engine": {"name": ENGINE_NAME, "version": engine_version()},
            "adapter_version": ADAPTER_VERSION,
            "field_mapping_version": FIELD_MAPPING_VERSION,
        }
    )


def experiment_dir(h: str) -> Path:
    return experiments_dir() / h


def load_outcome(h: str) -> CropOutcome | None:
    p = experiment_dir(h) / "outcome.json"
    if not p.exists():
        return None
    return CropOutcome.model_validate_json(p.read_text())


def load_trajectory(outcome: CropOutcome) -> pd.DataFrame:
    return pd.read_parquet(experiments_dir() / outcome.trajectory_ref)


def make_experiment(
    crop_profile_id: str,
    soil_profile_id: str,
    weather_scenario_id: str,
    weather_sha256: str,
    sim_start: date,
    sim_end: date,
    application_efficiency: float,
    schedule: Sequence[tuple[date, float]],
) -> CropExperiment:
    return CropExperiment(
        crop_profile_id=crop_profile_id,
        soil_profile_id=soil_profile_id,
        weather_scenario_id=weather_scenario_id,
        weather_sha256=weather_sha256,
        sim_start=sim_start,
        sim_end=sim_end,
        application_efficiency=application_efficiency,
        schedule=[{"date": d, "gross_depth_mm": float(v)} for d, v in schedule],
        engine_version=engine_version(),
        adapter_version=ADAPTER_VERSION,
    )


def _execute(
    exp: CropExperiment, crop: CropProfile, soil: SoilProfile, weather: pd.DataFrame | None = None
) -> CropOutcome:
    h = crop_experiment_hash(exp, crop, soil)
    cached = load_outcome(h)
    if cached is not None:
        return cached
    if exp.adapter_version != ADAPTER_VERSION:
        raise CropAdapterError(f"experiment adapter {exp.adapter_version} != {ADAPTER_VERSION}")
    w = weather if weather is not None else load_weather(exp.weather_sha256)
    t0 = time.perf_counter()
    res = CropSimulatorAdapter(crop, soil).evaluate(exp, w)
    wall = time.perf_counter() - t0
    final = experiment_dir(h)
    tmp = experiments_dir() / f".tmp-{h}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    refs = []
    for name, df in res.raw.items():
        fn = f"raw_{name}.parquet"
        out = df.copy()
        for c in out.columns:  # keep original names; make object columns parquet-safe
            if out[c].dtype == object:
                out[c] = out[c].astype(str)
        out.to_parquet(tmp / fn, index=False)
        refs.append(f"{h}/{fn}")
    res.trajectory.to_parquet(tmp / "trajectory.parquet", index=False)
    evidence_id = f"ev-exp-{h[:16]}"
    outcome = CropOutcome(
        experiment_hash=h,
        engine_name=ENGINE_NAME,
        engine_version=engine_version(),
        adapter_version=ADAPTER_VERSION,
        executed_at=datetime.now(UTC),
        crop_profile_id=crop.crop_profile_id,
        soil_profile_id=soil.soil_profile_id,
        weather_sha256=exp.weather_sha256,
        schedule_hash=schedule_hash(exp),
        planting_date=res.planting_date,
        actual_harvest_date=res.harvest_date,
        has_finished=res.has_finished,
        yield_basis=crop.yield_basis,
        yield_kg_ha=res.yield_kg_ha,
        seasonal_irrigation_mm=res.seasonal_irrigation_mm,
        raw_output_refs=refs,
        trajectory_ref=f"{h}/trajectory.parquet",
        field_mapping_version=FIELD_MAPPING_VERSION,
        warnings=res.warnings,
        evidence_id=evidence_id,
    )
    (tmp / "experiment.json").write_text(exp.model_dump_json(indent=2))
    (tmp / "evidence.json").write_text(
        json.dumps(
            {
                "evidence_id": evidence_id,
                "source_title": f"AquaCrop-OSPy {engine_version()} run {h[:12]}",
                "kind": "model_output",
                "verification_state": "artifact_checked",
                "method_version": ADAPTER_VERSION,
                "units": "yield kg/ha (from tonne/ha x1000), depths mm/day",
                "limitations": [
                    f"Crop profile {crop.crop_profile_id} is {crop.calibration_status}.",
                    "Simulated yield, not a measured harvest.",
                ],
                "wall_s": round(wall, 4),
                "raw_yield_t_ha": res.yield_t_ha_raw,
            },
            indent=2,
        )
    )
    (tmp / "outcome.json").write_text(outcome.model_dump_json(indent=2))
    try:
        tmp.rename(final)
    except OSError:  # another worker published the same hash first
        shutil.rmtree(tmp, ignore_errors=True)
        existing = load_outcome(h)
        if existing is None:
            raise
        return existing
    return outcome


def run_experiment(exp: CropExperiment) -> CropOutcome:
    """Cached exact crop run (STREAMS.md entry point)."""
    cp, sp = _resolved(exp)
    return _execute(exp, cp, sp)


# --------------------------------------------------------------------------- batch


@dataclass(frozen=True)
class BatchItem:
    experiment: CropExperiment
    crop: CropProfile
    soil: SoilProfile


@dataclass
class BatchReport:
    total: int
    cached: int
    executed: int
    failed: dict[str, str]
    wall_s: float
    outcomes: dict[str, CropOutcome]  # hash -> outcome


def _warmup() -> None:
    """Pool initializer: one small run compiles numba; excluded from timing (T5.2)."""
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from aquacrop.core import AquaCropModel
    from aquacrop.entities.crop import Crop
    from aquacrop.entities.inititalWaterContent import InitialWaterContent
    from aquacrop.entities.soil import Soil
    from aquacrop.utils.data import get_filepath
    from aquacrop.utils.prepare_weather import prepare_weather

    w = prepare_weather(get_filepath("tunis_climate.txt"))
    m = AquaCropModel(
        "1979/10/01",
        "1980/05/30",
        w,
        Soil("SandyLoam"),
        Crop("Wheat", planting_date="10/01"),
        InitialWaterContent(value=["FC"]),
    )
    m.run_model(till_termination=True)


_WEATHER_CACHE: dict[str, pd.DataFrame] = {}


def _worker(item: BatchItem) -> tuple[str, CropOutcome | None, str | None]:
    h = crop_experiment_hash(item.experiment, item.crop, item.soil)
    try:
        sha = item.experiment.weather_sha256
        if sha not in _WEATHER_CACHE:
            _WEATHER_CACHE[sha] = load_weather(sha)
        return h, _execute(item.experiment, item.crop, item.soil, _WEATHER_CACHE[sha]), None
    except Exception as exc:  # noqa: BLE001 - reported per experiment, never swallowed
        return h, None, f"{type(exc).__name__}: {exc}"


def default_workers() -> int:
    env = os.environ.get("AABFLOW_SCIENCE_WORKERS")
    if env:
        return max(1, int(env))
    return max(1, min(10, (os.cpu_count() or 2) - 4))


def run_batch(
    experiments: Iterable[CropExperiment],
    *,
    workers: int | None = None,
    progress: bool = False,
) -> BatchReport:
    t0 = time.perf_counter()
    items: dict[str, BatchItem] = {}
    for exp in experiments:
        cp, sp = _resolved(exp)
        items.setdefault(crop_experiment_hash(exp, cp, sp), BatchItem(exp, cp, sp))
    outcomes: dict[str, CropOutcome] = {}
    todo: list[BatchItem] = []
    for h, it in items.items():
        o = load_outcome(h)
        if o is not None:
            outcomes[h] = o
        else:
            todo.append(it)
    cached = len(outcomes)
    failed: dict[str, str] = {}
    n = workers or default_workers()
    if todo:
        if n <= 1 or len(todo) < 4:
            for it in todo:
                h, o, err = _worker(it)
                if o is not None:
                    outcomes[h] = o
                else:
                    failed[h] = err or "unknown"
        else:
            with ProcessPoolExecutor(max_workers=n, initializer=_warmup) as pool:
                futs = [pool.submit(_worker, it) for it in todo]
                for i, fut in enumerate(as_completed(futs), 1):
                    h, o, err = fut.result()
                    if o is not None:
                        outcomes[h] = o
                    else:
                        failed[h] = err or "unknown"
                    if progress and i % 200 == 0:
                        print(
                            f"  experiments {i}/{len(todo)} ({time.perf_counter() - t0:.0f}s)",
                            flush=True,
                        )
    return BatchReport(
        total=len(items),
        cached=cached,
        executed=len(todo) - len(failed),
        failed=failed,
        wall_s=time.perf_counter() - t0,
        outcomes=outcomes,
    )


def sim_window_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
