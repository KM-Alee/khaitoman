"""AT09/AT10: one six-setting frontier and one nine-cell stress on the real pilot-a library.

Talks to a running API over HTTP (default ``http://127.0.0.1:8000``), so every point and cell
is an ordinary run record in that server's database. After the jobs finish, each child
``run_id`` is fetched back through ``GET /runs/{id}`` and the result is written to
``evidence/benchmarks/analyses-<UTC>.json``. Nothing is retrained and no library is rebuilt.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SEASON = "wheat-rabi-2027-28"
REQ = {
    "pilot_id": "pilot-a",
    "pilot_version": "reviewed-v1",
    "season_id": SEASON,
    "planning_mode": "capital_planning",
    "decision_at": "2026-10-10T08:00:00+05:00",
    "weather_scenario_ids": ["dry", "typical", "wet"],
    "supply_profile_id": "nominal-roster-v1",
    "capital_budget_pkr": 3000000,
    "operating_budget_pkr": 400000,
    "uncertainty_set_id": f"pilot-a:{SEASON}:release-9",
}
FRONTIER_SETTINGS = [{"capital_budget_pkr": v} for v in (0, 500000, 1500000, 3000000, 8000000)] + [
    {"capital_budget_pkr": 3000000, "minimum_service_ratio": 0.95, "service_group": "tail"}
]
DONE = ("succeeded", "failed", "cancelled", "interrupted")


def wait(c: httpx.Client, job_id: str, timeout: float) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        j = c.get(f"/api/v2/jobs/{job_id}").json()
        if j["state"] in DONE:
            return j
        time.sleep(0.5)
    raise SystemExit(f"job {job_id} did not finish in {timeout:.0f} s: {j}")


def solve(c: httpx.Client, rid: str, kind: str) -> dict:
    r = c.post(
        f"/api/v2/scenario-revisions/{rid}/solve", json={"plan_kind": kind, "time_limit_s": 30}
    )
    r.raise_for_status()
    j = wait(c, r.json()["job_id"], 900)
    if j["state"] != "succeeded":
        raise SystemExit(f"{kind} solve did not succeed: {j}")
    return c.get(f"/api/v2/runs/{j['result_ref']}").json()


def analyse(c: httpx.Client, kind: str, body: dict) -> tuple[dict, float]:
    t0 = time.monotonic()
    a = c.post(f"/api/v2/analyses/{kind}", json=body)
    if a.status_code != 202:
        raise SystemExit(f"{kind} rejected: {a.status_code} {a.text}")
    j = wait(c, a.json()["job_id"], 1800)
    if j["state"] != "succeeded":
        raise SystemExit(f"{kind} job did not succeed: {j}")
    return c.get(f"/api/v2/analyses/{a.json()['analysis_id']}").json(), time.monotonic() - t0


def linked(c: httpx.Client, analysis_id: str, run_id: str | None) -> bool:
    """The child run exists as its own record and points back at the analysis."""
    if not run_id:
        return False
    r = c.get(f"/api/v2/runs/{run_id}")
    return r.status_code == 200 and r.json().get("analysis_id") == analysis_id


def metric(run: dict, mid: str):
    return next(
        (m["value"] for m in run["metrics"] if m["metric_id"] == mid and m["field_id"] is None),
        None,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or ROOT / "evidence" / "benchmarks" / f"analyses-{stamp}.json"

    with httpx.Client(base_url=args.base_url, timeout=60) as c:
        health = c.get("/api/v2/health").json()
        r = c.post("/api/v2/scenarios", json={"request": REQ})
        r.raise_for_status()
        rid = r.json()["revision"]["revision"]["scenario_revision_id"]
        runs = {k: solve(c, rid, k) for k in ("P", "R")}
        for k, run in runs.items():
            print(
                f"{k}: {run['run']['run_id']} {run['run']['outcome']} {run['run']['solver_status']}"
            )

        fr, fr_s = analyse(
            c,
            "frontier",
            {"base_revision_id": rid, "time_limit_per_point_s": 15, "settings": FRONTIER_SETTINGS},
        )
        st, st_s = analyse(
            c,
            "stress",
            {"run_id": runs["R"]["run"]["run_id"], "reference_run_id": runs["P"]["run"]["run_id"]},
        )

        sp, sp_s = analyse(c, "stress", {"run_id": runs["P"]["run"]["run_id"]})
        fid, sid, pid = fr["analysis_id"], st["analysis_id"], sp["analysis_id"]
        points = [
            {
                "point_id": p["point_id"],
                "setting": p["setting"],
                "run_id": p.get("run_id"),
                "run_record_linked": linked(c, fid, p.get("run_id")),
                "outcome": p.get("outcome"),
                "solver_status": p.get("solver_status"),
                "dominance": p.get("dominance"),
                "production_kg": p.get("production_kg"),
                "capital_commitment_pkr": p.get("capital_commitment_pkr"),
                "min_service_ratio": p.get("min_service_ratio"),
            }
            for p in fr["result"]["points"]
        ]
        r_sel = sorted(runs["R"]["run"]["selected_candidate_policy_ids"])
        cells = [
            {
                "state_id": x["state_id"],
                "run_id": x.get("run_id"),
                "run_record_linked": linked(c, sid, x.get("run_id")),
                "solver_status": x.get("solver_status"),
                "deliverable": x.get("deliverable"),
                "production_kg": x.get("production_kg"),
                "shares_robust_decisions": x.get("selected_candidate_policy_ids") is not None
                and sorted(x["selected_candidate_policy_ids"]) == r_sel,
                "violations": x.get("violations"),
            }
            for x in st["result"]["cells"]
        ]

        p_cells = [
            {
                "state_id": x["state_id"],
                "run_id": x.get("run_id"),
                "run_record_linked": linked(c, pid, x.get("run_id")),
                "deliverable": x.get("deliverable"),
                "production_kg": x.get("production_kg"),
                "violations": x.get("violations"),
            }
            for x in sp["result"]["cells"]
        ]

    at09 = len(points) == 6 and all(p["run_record_linked"] for p in points)
    undeliverable_ok = all(
        x["production_kg"] is None and x["violations"]
        for x in cells + p_cells
        if not x["deliverable"]
    ) and all(x["run_record_linked"] for x in p_cells)
    at10 = (
        len(cells) == 9
        and all(x["run_record_linked"] for x in cells)
        and all(x["shares_robust_decisions"] for x in cells if x["deliverable"])
        and undeliverable_ok
    )
    record = {
        "generated_at": stamp,
        "command": "docker compose exec api python scripts/analysis_evidence.py",
        "api": {"base_url": args.base_url, "versions": health.get("versions")},
        "scenario_request": REQ,
        "scenario_revision_id": rid,
        "source_runs": {
            k: {
                "run_id": v["run"]["run_id"],
                "plan_kind": v["run"]["plan_kind"],
                "outcome": v["run"]["outcome"],
                "solver_status": v["run"]["solver_status"],
                "production_kg": metric(v, "production_kg"),
                "worst_tested_production_kg": metric(v, "worst_tested_production_kg"),
            }
            for k, v in runs.items()
        },
        "frontier": {
            "analysis_id": fid,
            "wall_s": round(fr_s, 2),
            "counts": fr["result"].get("counts"),
            "proof_status": fr["result"].get("proof_status"),
            "label": fr["result"].get("label"),
            "points": points,
        },
        "stress": {
            "analysis_id": sid,
            "wall_s": round(st_s, 2),
            "mode": st["result"].get("mode"),
            "summary": st["result"].get("summary"),
            "matrix": st["result"].get("matrix"),
            "foregone_typical_output": st["result"].get("foregone_typical_output"),
            "cells": cells,
        },
        "typical_plan_stress": {
            "analysis_id": pid,
            "wall_s": round(sp_s, 2),
            "summary": sp["result"].get("summary"),
            "cells": p_cells,
        },
        "checks": {
            "AT09_six_points_each_a_linked_run": at09,
            "AT10_nine_cells_linked_shared_decisions_no_yield_when_undeliverable": at10,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record["checks"], indent=2))
    print(f"wrote {out.relative_to(ROOT)}")
    return 0 if at09 and at10 else 1


if __name__ == "__main__":
    sys.exit(main())
