"""Run the Delineate inference an onboarding intake is waiting for (vision container).

Usage:
    docker compose -f compose.yaml -f vision/compose.vision.yaml --profile vision \
        run --rm --no-deps -T vision python /app/vision/run_pending.py /app/<intake workdir>

Reads <workdir>/processed/process_result.json, and runs vision/run_batch.py for its
inference key unless that key already has a successful run record (cache hit).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    wd = Path(sys.argv[1])
    res = json.loads((wd / "processed" / "process_result.json").read_text())
    inf = res["inference"]
    key = inf["inference_key"]
    record = Path(f"/app/vision/runs/{key}/run.json")
    if record.exists() and json.loads(record.read_text()).get("ok"):
        print(f"inference {key}: cached run record {record}")
        return 0
    cmd = [sys.executable, "/app/vision/run_batch.py", f"/app/{inf['batch']}",
           "--record", str(record), "--label", key]  # fmt: skip
    print(" ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
