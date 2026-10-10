"""Science batch: publish scenarios and build candidate libraries for every season of a pilot.

usage: python scripts/science_build_libraries.py <pilot_id> [season_id ...]
Writes data/libraries/<pilot>/<season>/<hash>/ and latest.json; prints build stats as JSON.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from aabflow.config import ROOT
from aabflow.optimizer.candidates import build_library, load_library
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
    bench = {"generated_at": datetime.now(UTC).isoformat(), "pilot_id": pilot, "seasons": {}}
    for sid, row in out.items():
        lib, pols = load_library(pilot, sid, row["library_hash"])
        per = Counter((p.field_id, p.shared_configuration_id) for p in pols)
        fams = Counter(p.family for p in pols)
        size = (Path(ROOT) / "data" / "libraries" / lib.policies_ref).stat().st_size
        bench["seasons"][sid] = {
            **row,
            "options_per_field": {f"{f}@{c}": n for (f, c), n in sorted(per.items())},
            "fields_below_24": sum(1 for n in per.values() if n < 24),
            "fields_above_60": sum(1 for n in per.values() if n > 60),
            "families": dict(fams),
            "policies_jsonl_mb": round(size / 1e6, 2),
            "excluded_instances": lib.excluded_instances,
            "configurations": [c.shared_configuration_id for c in lib.configurations],
        }
    path = (
        Path(ROOT)
        / "evidence"
        / "benchmarks"
        / f"science-library-{pilot}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bench, indent=1))
    print(json.dumps(out, indent=1))
    print(f"benchmark: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
