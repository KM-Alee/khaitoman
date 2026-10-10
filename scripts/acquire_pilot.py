"""Acquire real sources for a pilot AOI into an immutable raw bundle (T2.1-T2.6).

Examples (inside the api container):
    python scripts/acquire_pilot.py --pilot pilot-a
    python scripts/acquire_pilot.py --pilot pilot-b --bbox 72.234 30.657 72.256 30.677

Prints the bundle path (data/raw/bundles/<pilot>/<bundle_id>) on success and
exits nonzero on any failed source gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from aabflow.ingestion.aoi import Aoi  # noqa: E402
from aabflow.ingestion.onboarding.acquire import AcquisitionConfig, acquire_bundle  # noqa: E402
from aabflow.ingestion.pilot_aois import PILOTS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pilot", required=True, help="pilot id, e.g. pilot-a")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--aoi-geojson", type=Path, help="AOI polygon GeoJSON instead of --bbox")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--primary-window", nargs=2, default=AcquisitionConfig.primary_window)
    ap.add_argument("--secondary-window", nargs=2, default=AcquisitionConfig.secondary_window)
    ap.add_argument("--no-dem", action="store_true")
    ap.add_argument("--no-grain", action="store_true")
    args = ap.parse_args()

    cfgd = PILOTS.get(args.pilot)
    if args.aoi_geojson:
        aoi = Aoi.from_geojson(json.loads(args.aoi_geojson.read_text()))
    elif args.bbox:
        aoi = Aoi.from_bbox(*args.bbox)
    elif cfgd:
        aoi = Aoi.from_bbox(*cfgd.bbox)
    else:
        ap.error("unknown pilot: pass --bbox or --aoi-geojson")
    cfg = AcquisitionConfig(
        primary_window=tuple(args.primary_window),
        secondary_window=tuple(args.secondary_window),
        dem=not args.no_dem,
        grain=not args.no_grain,
    )
    print(f"AOI {aoi.bbox} area {aoi.area_m2 / 1e6:.3f} km² metric CRS {aoi.metric_crs_id}")

    def progress(stage, frac, detail):
        f = "" if frac is None else f" {frac:4.0%}"
        print(f"[{stage}]{f} {detail}", flush=True)

    root = acquire_bundle(
        args.pilot,
        aoi,
        args.data_dir,
        cfg,
        progress=progress,
        name=cfgd.name if cfgd else None,
        geographic_name_basis=cfgd.geographic_name_basis if cfgd else None,
    )
    print(root.relative_to(args.data_dir.parent) if root.is_relative_to(args.data_dir.parent) else root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
