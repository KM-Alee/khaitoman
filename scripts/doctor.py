"""`make doctor`: versions, assets, CPU/GPU, network and provider status (T13.4).

Runs in the api container; `make doctor` checks the web and vision containers
separately.

Exits nonzero when a required item is missing. Secrets are never printed; a
configured key is reported separately from a successful provider call, which
only runs with --provider-smoke.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DISTS = [
    "aquacrop",
    "ortools",
    "numpy",
    "pandas",
    "geopandas",
    "shapely",
    "pyproj",
    "pyarrow",
    "rasterio",
    "pystac-client",
    "httpx",
    "lightgbm",
    "scikit-learn",
    "fastapi",
    "pydantic",
    "uvicorn",
    "openai",
    "pytest",
    "hypothesis",
]
ENDPOINTS = {
    "pypi": "https://pypi.org/simple/",
    "earth_search": "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a",
    "open_meteo_archive": "https://archive-api.open-meteo.com/v1/archive?latitude=30.8&longitude=72.5&start_date=2024-01-01&end_date=2024-01-02&daily=temperature_2m_max&timezone=Asia%2FKarachi",
    "overpass": "https://overpass-api.de/api/status",
    "zenodo_grain": "https://zenodo.org/api/records/16786488",
    "huggingface": "https://huggingface.co/api/models/MykolaL/DelineateAnything",
    "openai": "https://api.openai.com/v1/models",
}


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _reachable(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aabflow-doctor"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"ok {r.status}"
    except urllib.error.HTTPError as e:  # reachable, but e.g. 401 without a key
        return f"reachable {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"failed {type(e).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--provider-smoke",
        action="store_true",
        help="call the OpenAI API with the configured model",
    )
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    missing: list[str] = []
    report: dict = {"generated_at": datetime.now(UTC).isoformat(), "machine": platform.platform()}

    report["python"] = sys.version.split()[0]
    if not report["python"].startswith("3.11."):
        missing.append("python 3.11 main env")

    dists = {}
    for d in REQUIRED_DISTS:
        try:
            dists[d] = version(d)
        except PackageNotFoundError:
            dists[d] = None
            missing.append(d)
    report["packages"] = dists

    weights = sorted(p.name for p in (ROOT / "data/models/delineate-anything").glob("*.pt"))
    report["delineate_weights"] = weights
    if not weights:
        missing.append("Delineate Anything weights")

    report["in_container"] = Path("/.dockerenv").exists()
    report["cpu_count"] = os.cpu_count()
    report["gpu"] = (
        _run(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
        or "unavailable"
    )
    report["disk_free_gb"] = round(shutil.disk_usage(ROOT).free / 1e9, 1)

    report["network"] = {k: _reachable(u) for k, u in ENDPOINTS.items()}

    key = bool(os.environ.get("OPENAI_API_KEY"))
    model = os.environ.get("AABFLOW_OPENAI_MODEL", "gpt-6.1-sol")
    provider = {"key_configured": key, "model": model, "smoke": "not_run"}
    if args.provider_smoke:
        if not key:
            provider["smoke"] = "skipped: no key"
        else:
            try:
                from openai import OpenAI

                OpenAI().models.retrieve(model)
                provider["smoke"] = "ok: model available"
            except Exception as e:  # noqa: BLE001
                provider["smoke"] = f"failed: {type(e).__name__}: {str(e)[:200]}"
    report["provider"] = provider

    report["missing"] = missing
    out = ROOT / "evidence/environment" / f"doctor-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(json.dumps(report, indent=2))
    print(f"\nSaved {out.relative_to(ROOT)}")
    if missing:
        print("MISSING: " + ", ".join(missing))
        return 1
    print("doctor: all required items present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
