"""One in-domain preview after model load, then a separate exact confirmation.

AquaCrop and this measurement stay on CPU. The seeded surrogate is not retrained.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from datetime import date, timedelta
from pathlib import Path

from aabflow.science.paths import models_dir
from aabflow.surrogate.domain import latest_version
from aabflow.surrogate.prediction import confirm, preview

OUT = Path(__file__).with_name("p04-preview-timing.json")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def request() -> dict:
    planting = date(2026, 11, 15)
    return {
        "crop_profile_id": "wheat-punjab-gdd-v1",
        "soil_profile_id": "aquacrop-siltloam-pct50",
        "application_efficiency": 0.6,
        "season_id": "wheat-rabi-2026-27",
        "weather_scenario_id": "typical",
        "schedule": [
            {"date": (planting + timedelta(days=d)).isoformat(), "gross_depth_mm": 50.0}
            for d in range(10, 110, 14)
        ],
    }


def main() -> None:
    version = latest_version()
    root = models_dir() / version
    summary = json.loads((root / "evaluation.json").read_text())
    crops = {}
    for crop in ("wheat", "cotton"):
        ev = json.loads((root / f"evaluation-{crop}.json").read_text())
        artifacts = ev["artifacts"]
        model = root / artifacts["model"]
        data = root / artifacts["training_data"]
        model_hash = sha256(model)
        data_hash = sha256(data)
        crops[crop] = {
            "training_device": ev.get("training_device"),
            "passed": ev.get("passed"),
            "gate_results": ev.get("gate_results"),
            "test_year": ev["split_manifest"]["test_year"],
            "holdout_family": ev["split_manifest"].get("holdout_family"),
            "test_nmae": ev["test"]["nmae"],
            "model_sha256": model_hash,
            "model_sha256_matches_record": model_hash == artifacts["model_sha256"],
            "training_data_sha256": data_hash,
            "training_data_sha256_matches_record": data_hash == artifacts["training_data_sha256"],
        }
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(root / "model-wheat.txt"))
    params = booster.params
    gpu_present = any(Path("/dev").glob("nvidia*"))
    # A stored training device_type is not the device that executed this predict.
    inference_device = "gpu" if gpu_present else "cpu"
    req = request()
    preview(req)  # load model, features, and weather; excluded from the timed call
    started = time.perf_counter()
    pv = preview(req)
    elapsed_ms = (time.perf_counter() - started) * 1000
    outcome, confirmed, diff = confirm(req)
    record = {
        "node": "P04",
        "model_version": version,
        "training_device_recorded": summary.get("training_device"),
        "model_parameter_device_type": params.get("device_type"),
        "gpu_device_present": gpu_present,
        "inference_device_observed": inference_device,
        "inference_note": "Seeded model file records device_type=gpu from training. This preview ran Booster.predict with no NVIDIA device in the container, so inference was CPU. AquaCrop confirmation is a separate CPU result.",
        "host": platform.platform(),
        "thread_caps": {
            "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
            "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
            "AABFLOW_SCIENCE_WORKERS": os.environ.get("AABFLOW_SCIENCE_WORKERS"),
        },
        "preview": {
            "estimate_kind": pv.estimate_kind,
            "domain_status": pv.domain_status,
            "model_version": pv.model_version,
            "feature_version": pv.feature_version,
            "evaluation_reference": pv.evaluation_reference,
            "estimated_yield_kg_ha": pv.estimated_yield_kg_ha,
            "preview_id": pv.preview_id,
            "elapsed_ms_after_load": elapsed_ms,
            "within_300_ms": elapsed_ms <= 300,
        },
        "exact_confirmation": {
            "estimate_kind": "exact_crop_model",
            "preview_estimate_kind": confirmed.estimate_kind,
            "distinct_from_preview": confirmed.estimate_kind == "surrogate_preview"
            and outcome.yield_kg_ha is not None,
            "exact_yield_kg_ha": outcome.yield_kg_ha,
            "preview_minus_exact_kg_ha": diff,
            "experiment_hash": outcome.experiment_hash,
            "evidence_id": outcome.evidence_id,
            "has_finished": outcome.has_finished,
            "executed_at": outcome.executed_at.isoformat(),
            "engine_name": outcome.engine_name,
            "aquacrop_device": "cpu",
        },
        "held_out": crops,
        "evaluation_passed": summary.get("passed"),
    }
    OUT.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"elapsed_ms_after_load": elapsed_ms, "within_300_ms": elapsed_ms <= 300, "out": str(OUT)}))


if __name__ == "__main__":
    main()
