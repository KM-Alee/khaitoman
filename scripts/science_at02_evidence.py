"""AT02 evidence: wheat and cotton runs with raw outputs, known units and varying irrigation.

Real AquaCrop runs on ERA5 (Open-Meteo archive) weather at the Lower Chenab discovery point,
historical seasons rabi 2023-24 and kharif 2023. Writes data/experiments/_evidence/at02.json.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from aabflow.science.experiments import experiment_dir, make_experiment, run_experiment
from aabflow.science.paths import atomic_write_text, experiments_dir
from aabflow.science.scenarios import weather_source
from aabflow.science.weather import slice_window, store_weather

RUNS = {
    "wheat-punjab-gdd-v1": (
        date(2023, 11, 1),
        date(2024, 5, 31),
        {
            "rainfed": [],
            "3x75mm": [
                (date(2023, 12, 5), 75.0),
                (date(2024, 1, 15), 75.0),
                (date(2024, 2, 20), 75.0),
            ],
            "5 turns 50-60mm": [
                (date(2023, 11, 25), 50.0),
                (date(2023, 12, 20), 50.0),
                (date(2024, 1, 25), 60.0),
                (date(2024, 2, 15), 60.0),
                (date(2024, 3, 5), 60.0),
            ],
        },
    ),
    "cotton-punjab-v1": (
        date(2023, 4, 17),
        date(2023, 12, 15),
        {
            "rainfed": [],
            "3x75mm": [
                (date(2023, 5, 20), 75.0),
                (date(2023, 6, 15), 75.0),
                (date(2023, 7, 10), 75.0),
            ],
            "6x60mm": [
                (date(2023, 5, 15), 60.0),
                (date(2023, 6, 5), 60.0),
                (date(2023, 6, 25), 60.0),
                (date(2023, 7, 15), 60.0),
                (date(2023, 8, 10), 60.0),
                (date(2023, 9, 5), 60.0),
            ],
        },
    ),
}


def main() -> int:
    src = weather_source(None)
    rows = []
    for crop, (start, end, treatments) in RUNS.items():
        sha, _ = store_weather(slice_window(src.frame, start, end))
        for name, sched in treatments.items():
            o = run_experiment(
                make_experiment(
                    crop, "aquacrop-siltloam-pct50", "historical", sha, start, end, 0.6, sched
                )
            )
            rows.append(
                {
                    "crop_profile_id": crop,
                    "treatment": name,
                    "experiment_hash": o.experiment_hash,
                    "yield_kg_ha": round(o.yield_kg_ha, 1),
                    "yield_basis": o.yield_basis,
                    "seasonal_irrigation_mm": o.seasonal_irrigation_mm,
                    "harvest": o.actual_harvest_date.isoformat(),
                    "raw_output_refs": o.raw_output_refs,
                    "dir": str(
                        experiment_dir(o.experiment_hash).relative_to(experiments_dir().parent)
                    ),
                }
            )
    doc = {
        "generated_at": datetime.now(UTC).isoformat(),
        "weather": src.origin,
        "series": src.series_id,
        "grid_cell": src.grid_cell,
        "soil": "AquaCrop SiltLoam, 50% TAW at sim start",
        "app_eff": 0.6,
        "units": "yield kg/ha (AquaCrop tonne/ha x 1000, once); irrigation gross mm",
        "runs": rows,
    }
    atomic_write_text(experiments_dir() / "_evidence" / "at02.json", json.dumps(doc, indent=1))
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
