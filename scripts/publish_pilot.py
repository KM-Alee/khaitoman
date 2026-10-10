"""Run a pilot through the onboarding pipeline and publish it (T2.6, F03, AT16).

Stages: import raw bundle (or acquire online) → process → [Delineate in the
vision container] → review → validate → publish to data/pilots/<pilot>/<version>/.

The api container cannot start the vision container, so a first call stops with
exit code 3 when the matching inference is not cached and prints the command;
``vision/run_pending.py`` (vision container) executes it, then rerun this script.

Examples (inside the api container):
    python scripts/publish_pilot.py --pilot pilot-a --version reviewed-v1
    python scripts/publish_pilot.py --pilot pilot-b --version reviewed-v1 \
        --bundle data/raw/bundles/pilot-b/<bundle_id> --until process
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from aabflow.ingestion.common import read_json  # noqa: E402
from aabflow.ingestion.onboarding import pipeline  # noqa: E402
from aabflow.ingestion.pilot_aois import PILOTS  # noqa: E402

EXIT_AWAITING_INFERENCE = 3


def latest_bundle(data_dir: Path, pilot: str) -> Path:
    root = data_dir / "raw" / "bundles" / pilot
    cands = sorted(p for p in root.glob("*") if p.is_dir() and not p.name.endswith(".partial"))
    if not cands:
        raise SystemExit(f"no raw bundle under {root}; run scripts/acquire_pilot.py first")
    return cands[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pilot", required=True)
    ap.add_argument("--version", default="reviewed-v1")
    ap.add_argument("--bundle", type=Path, help="raw bundle dir (default: latest for the pilot)")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--workdir", type=Path, help="intake workdir (default data/pilots/.intake/<pilot>-<version>)")
    ap.add_argument("--edits", type=Path, help="reviewer edits JSON (default data/pilots/review_edits/<pilot>.json)")
    ap.add_argument("--reviewer", default=None)
    ap.add_argument("--until", choices=["process", "review", "publish"], default="publish")
    args = ap.parse_args()

    meta = PILOTS.get(args.pilot)
    bundle = (args.bundle if args.bundle else latest_bundle(args.data_dir, args.pilot)).resolve()
    wd = args.workdir or args.data_dir / "pilots" / ".intake" / f"{args.pilot}-{args.version}"
    rel_bundle = str(bundle.relative_to(ROOT.resolve()))

    def progress(stage, frac, detail):
        print(f"[{stage}]{'' if frac is None else f' {frac:4.0%}'} {detail}", flush=True)

    if not (wd / "intake.json").exists():
        aoi = json.loads((bundle / "aoi.geojson").read_text())
        st = pipeline.create_intake(
            f"{args.pilot}-{args.version}", aoi, "raw_package", rel_bundle, wd,
            name=meta.name if meta else None, pilot_id=args.pilot,
            geographic_name_basis=meta.geographic_name_basis if meta else None,
            parent_canal_feature_id=f"osm:way/{meta.parent_canal_osm_way}" if meta else None,
        )  # fmt: skip
        print(f"intake created: {wd} ({st['state']})")
    st = pipeline.status(wd)
    if st["state"] in ("created", "awaiting_inference", "failed", "acquired_raw"):
        out = pipeline.process(st["intake_id"], wd, progress=progress)
        print(json.dumps({k: out[k] for k in ("state", "blockers", "warnings", "cache_hits")}, indent=1))
        if out["state"] == "awaiting_inference":
            print("run in the vision container:\n  " + out["inference_command"])
            return EXIT_AWAITING_INFERENCE
        if out.get("review_summary"):
            print(json.dumps(out["review_summary"], indent=1))
    if args.until == "process":
        return 0
    st = pipeline.status(wd)
    if st["state"] == "needs_review":
        ep = args.edits or args.data_dir / "pilots" / "review_edits" / f"{args.pilot}.json"
        edits = read_json(ep) if ep.exists() else {"field_edits": []}
        if args.reviewer:
            edits["reviewer"] = args.reviewer
        edits.setdefault("reviewer", "aabflow data stream (rule-based review + visual overlay check)")
        r = pipeline.apply_review(wd, edits, st["review_version"])
        print(json.dumps(r, indent=1))
        if r["blockers"]:
            return 2
    if args.until == "review":
        return 0
    m = pipeline.publish(wd, args.pilot, args.version, data_dir=args.data_dir)
    print(f"published {args.pilot}/{args.version}: {len(m.files)} files, {len(m.source_ids)} source ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
