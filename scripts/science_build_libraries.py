"""Science batch: publish scenarios and build candidate libraries for every season of a pilot.

usage: python scripts/science_build_libraries.py <pilot_id> [season_id ...]
Writes data/libraries/<pilot>/<season>/<hash>/ and latest.json; prints build stats as JSON.
"""

from __future__ import annotations

import json
import sys
import time

from aabflow.optimizer.candidates import build_library
from aabflow.science import crop_profiles, scenarios


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pilot = sys.argv[1]
    seasons = sys.argv[2:] or list(crop_profiles.SEASONS)
    pilots = sorted({p for p, _ in scenarios.published_pilots()} | {pilot})
    scenarios.publish(pilots)
    out = {}
    for sid in seasons:
        t = time.perf_counter()
        lib = build_library(pilot, sid, progress=True)
        out[sid] = {
            "library_hash": lib.candidate_library_hash,
            "wall_s": round(time.perf_counter() - t, 1),
            **lib.build_stats,
        }
        print(json.dumps({sid: out[sid]}, indent=1), flush=True)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
