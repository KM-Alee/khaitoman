"""M0 benchmark: time real AquaCrop wheat runs on Open-Meteo weather for a Lower Chenab point.

Writes evidence/benchmarks/crop-bench-<ts>.json. Excludes the numba warm-up run (T5.2).
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from aquacrop.core import AquaCropModel
from aquacrop.entities.crop import Crop
from aquacrop.entities.inititalWaterContent import InitialWaterContent
from aquacrop.entities.irrigationManagement import IrrigationManagement
from aquacrop.entities.soil import Soil

ROOT = Path(__file__).resolve().parents[1]
LAT, LON = 30.8, 72.5  # inside the published Mungi search extent (discovery only)


def weather(start: str, end: str) -> pd.DataFrame:
    r = httpx.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": LAT,
            "longitude": LON,
            "start_date": start,
            "end_date": end,
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,et0_fao_evapotranspiration",
            "timezone": "Asia/Karachi",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()["daily"]
    return pd.DataFrame(
        {
            "MinTemp": d["temperature_2m_min"],
            "MaxTemp": d["temperature_2m_max"],
            "Precipitation": d["precipitation_sum"],
            "ReferenceET": d["et0_fao_evapotranspiration"],
            "Date": pd.to_datetime(d["time"]),
        }
    )


def run(wdf: pd.DataFrame, schedule: pd.DataFrame | None) -> float:
    if schedule is None:
        irr = IrrigationManagement(irrigation_method=0)
    else:
        irr = IrrigationManagement(
            irrigation_method=3,
            Schedule=schedule.copy(),
            AppEff=70.0,
            MaxIrr=120.0,
            MaxIrrSeason=1200.0,
        )
        assert irr.Schedule.equals(schedule)
    m = AquaCropModel(
        "2022/11/01",
        "2023/07/31",
        wdf,
        Soil("SiltLoam"),
        Crop("Wheat", planting_date="11/15"),
        InitialWaterContent(value=["FC"]),
        irrigation_management=irr,
    )
    m.run_model(till_termination=True)
    res = m.get_simulation_results()
    return float(res["Dry yield (tonne/ha)"].iloc[0])


def main() -> None:
    wdf = weather("2022-11-01", "2023-07-31")
    sched = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2022-12-10", "2023-01-20", "2023-02-25", "2023-03-20"]),
            "Depth": [75.0] * 4,
        }
    )
    t0 = time.perf_counter()
    run(wdf, None)
    warm = time.perf_counter() - t0
    times, yields = [], {}
    for i in range(10):
        t = time.perf_counter()
        y = run(wdf, None if i % 2 == 0 else sched)
        times.append(time.perf_counter() - t)
        yields["rainfed" if i % 2 == 0 else "4x75mm"] = y
    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "point": [LAT, LON],
        "season": "wheat 2022-23",
        "warmup_s": round(warm, 3),
        "runs": len(times),
        "median_s": round(statistics.median(times), 3),
        "p95_s": round(sorted(times)[int(0.95 * (len(times) - 1))], 3),
        "dry_yield_t_ha": yields,
    }
    path = ROOT / "evidence/benchmarks" / f"crop-bench-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
