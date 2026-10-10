"""Publish seasons, crop profiles, weather scenarios and supply/uncertainty libraries.

Uses pilot-package weather when published (data/pilots/*/<version>/weather), otherwise
the science discovery-point Open-Meteo archive fetch; pilots in one grid cell share files.
"""

from __future__ import annotations

import json
import sys

from aabflow.science import scenarios


def main() -> int:
    pilots = sys.argv[1:] or None
    doc = scenarios.publish(pilots)
    summary = {
        "default_grid_cell": doc["default_grid_cell"],
        "pilot_grid_cells": doc["pilot_grid_cells"],
        "scenarios": [
            (s["season_id"], s["weather_scenario_id"], s["analog_season_label"],
             s["statistics"].get("p_minus_et0_mm"))
            for s in doc["scenarios"]
        ],
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
