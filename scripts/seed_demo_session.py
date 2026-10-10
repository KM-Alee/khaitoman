"""Seed the guided demo tour with real, executed results (``make demo-seed``).

Talks to a running API over HTTP (default ``http://127.0.0.1:8000``), so every ID it records is
an ordinary scenario, revision, run or analysis in that server's database:

1. health check (versions recorded);
2. one pilot-a / reviewed-v1 capital-planning scenario on the published library;
3. B0, B1, P and R solved on that revision;
4. a child revision with a lower capital budget that changes the selected P portfolio
   (budgets are tried in order; the one used and why is recorded), solved for B0, B1 and P;
5. a six-setting frontier on the base revision and a stress test of R against P;
6. a focus field picked from the server's B0 -> P comparison (largest positive field production
   delta in the tail group) and, when the server's P timeline gives a basis, a decisive date;
7. with ``--plan-goal "<sentence>"``: one "Plan my season" copilot turn (mode=plan, the hosted model
   and the real tools) on the base revision and its P run, waited to completion; its turn ID, goal and
   finish time are stored as ``plan_turn_id``/``plan_goal``/``plan_computed_at`` so the UI can replay
   the saved investigation. ``--plan-only`` adds that turn to an existing manifest without re-solving.

Any failed job, rejected request or non-plan outcome exits non-zero before a manifest is written.
The manifest goes to ``data/demo/session.json`` (gitignored: it names records that live only in
the local ``app.sqlite`` and ``data/runs``) and is served by ``GET /api/v2/demo/session``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from aabflow.api.demo import DemoManifest

ROOT = Path(__file__).resolve().parents[1]

SEASON = "wheat-rabi-2027-28"
BASE_CAPITAL_PKR = 3_000_000
REQ: dict[str, Any] = {
    "pilot_id": "pilot-a",
    "pilot_version": "reviewed-v1",
    "season_id": SEASON,
    "planning_mode": "capital_planning",
    "decision_at": "2026-10-10T08:00:00+05:00",
    "weather_scenario_ids": ["dry", "typical", "wet"],
    "supply_profile_id": "nominal-roster-v1",
    "capital_budget_pkr": BASE_CAPITAL_PKR,
    "operating_budget_pkr": 400_000,
    "uncertainty_set_id": f"pilot-a:{SEASON}:release-9",
}
# Lower capital budgets tried in order for the budget-change child revision.
CHILD_BUDGETS_PKR = (500_000, 1_500_000, 1_000_000, 0)
FRONTIER_SETTINGS = [
    {"capital_budget_pkr": v} for v in (0, 500_000, 1_500_000, 3_000_000, 8_000_000)
]
FRONTIER_SETTINGS.append(
    {"capital_budget_pkr": BASE_CAPITAL_PKR, "minimum_service_ratio": 0.95, "service_group": "tail"}
)
FOCUS_GROUP = "tail"
DONE = ("succeeded", "failed", "cancelled", "interrupted")
# A job the server cancelled or interrupted (the dev API's --reload restarts the dispatcher on any
# file change, which cancels active jobs) is resubmitted up to this many times in total. A job
# that *fails* is never retried.
MAX_ATTEMPTS = 4
RESUBMIT = ("cancelled", "interrupted")
NOTES: list[str] = []
# A plan-mode turn has a 240 s wall budget; allow for queueing and the post-turn job follow-up.
PLAN_TURN_TIMEOUT_S = 420.0


class SeedError(SystemExit):
    def __init__(self, msg: str):
        super().__init__(f"demo-seed FAILED: {msg}")


def call(c: httpx.Client, method: str, path: str, ok: tuple[int, ...] = (200,), **kw) -> Any:
    r = c.request(method, path, **kw)
    if r.status_code not in ok:
        raise SeedError(f"{method} {path} -> {r.status_code}: {r.text[:2000]}")
    return r.json()


def wait(c: httpx.Client, job_id: str, timeout: float) -> dict:
    t0 = time.monotonic()
    j: dict = {}
    while time.monotonic() - t0 < timeout:
        j = call(c, "GET", f"/api/v2/jobs/{job_id}")
        if j["state"] in DONE:
            return j
        time.sleep(0.5)
    raise SeedError(f"job {job_id} did not finish in {timeout:.0f} s (last state {j.get('state')})")


def metric(view: dict, mid: str) -> float | None:
    return next(
        (m["value"] for m in view["metrics"] if m["metric_id"] == mid and m["field_id"] is None),
        None,
    )


def run_job(c: httpx.Client, label: str, submit, timeout: float) -> tuple[dict, dict]:
    """POST via ``submit()`` and wait; resubmit only when the server cancelled/interrupted it."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        acc = submit()
        j = wait(c, acc["job_id"], timeout)
        if j["state"] == "succeeded":
            return acc, j
        if j["state"] in RESUBMIT and attempt < MAX_ATTEMPTS:
            note = (
                f"{label}: job {j['job_id']} {j['state']} at stage {j.get('stage')!r} "
                f"(attempt {attempt}); resubmitted"
            )
            NOTES.append(note)
            print(f"  note: {note}")
            continue
        raise SeedError(f"{label}: job {j['job_id']} {j['state']}: {j.get('error')}")
    raise AssertionError("unreachable")


def solve(c: httpx.Client, rid: str, kind: str, time_limit_s: float) -> dict:
    _, j = run_job(
        c,
        f"{kind} solve on {rid}",
        lambda: call(
            c,
            "POST",
            f"/api/v2/scenario-revisions/{rid}/solve",
            ok=(202,),
            json={"plan_kind": kind, "time_limit_s": time_limit_s},
        ),
        900,
    )
    view = call(c, "GET", f"/api/v2/runs/{j['result_ref']}")
    run = view["run"]
    if run["outcome"] != "plan":
        raise SeedError(
            f"{kind} solve on {rid} produced run {run['run_id']} with outcome {run['outcome']} "
            f"({run['solver_status']}); the demo needs validated plans"
        )
    print(
        f"  {kind}: {run['run_id']} {run['solver_status']} "
        f"production_kg={metric(view, 'production_kg')}"
    )
    return view


def analyse(c: httpx.Client, kind: str, body: dict) -> dict:
    acc, _ = run_job(
        c,
        f"{kind} analysis",
        lambda: call(c, "POST", f"/api/v2/analyses/{kind}", ok=(202,), json=body),
        1800,
    )
    a = call(c, "GET", f"/api/v2/analyses/{acc['analysis_id']}")
    if a["status"] != "completed":
        raise SeedError(f"{kind} analysis {a['analysis_id']} status {a['status']}")
    print(f"  {kind}: {a['analysis_id']} ({len(a['child_run_ids'])} child runs)")
    return a


def portfolio(view: dict) -> tuple:
    run = view["run"]
    return (
        tuple(sorted(run["selected_intervention_instance_ids"])),
        tuple(sorted(run["selected_candidate_policy_ids"])),
    )


def portfolio_change(budget: int, base: dict, child: dict) -> str:
    """Server-reported difference between two P runs, as a short sentence."""
    a = set(base["run"]["selected_intervention_instance_ids"])
    b = set(child["run"]["selected_intervention_instance_ids"])
    parts = []
    if a - b:
        parts.append(f"drops {sorted(a - b)}")
    if b - a:
        parts.append(f"adds {sorted(b - a)}")
    if not parts:
        parts.append("keeps the same interventions but selects different candidate policies")

    def fmt(v: float | None) -> str:
        return "n/a" if v is None else f"{v:,.0f}"

    return (
        f"capital budget {budget:,} PKR (from {BASE_CAPITAL_PKR:,}) changes the P portfolio: "
        f"{'; '.join(parts)}; capital commitment {fmt(metric(base, 'capital_commitment_pkr'))} -> "
        f"{fmt(metric(child, 'capital_commitment_pkr'))} PKR; production "
        f"{fmt(metric(base, 'production_kg'))} -> {fmt(metric(child, 'production_kg'))} kg"
    )


def detail(view: dict) -> dict:
    run = view["run"]
    return {
        "plan_kind": run["plan_kind"],
        "outcome": run["outcome"],
        "solver_status": run["solver_status"],
        "created_at": run["created_at"],
        "production_kg": metric(view, "production_kg"),
        "capital_commitment_pkr": metric(view, "capital_commitment_pkr"),
        "selected_intervention_instance_ids": run.get("selected_intervention_instance_ids", []),
    }


def pick_focus(c: httpx.Client, b0: str, p: str, groups: dict[str, str]) -> tuple[str, str, str]:
    cmp = call(c, "POST", "/api/v2/comparisons", ok=(201,), json={"run_ids": [b0, p]})
    tail = sorted(f for f, g in groups.items() if g == FOCUS_GROUP)
    if not tail:
        raise SeedError(f"pilot map has no {FOCUS_GROUP}-group fields")
    rows = [
        d
        for d in cmp["deltas"]
        if d["metric_id"] == "field_production_kg"
        and d["field_id"] in tail
        and d["delta"] is not None
        and d["delta"] > 0
    ]
    if rows:
        best = max(rows, key=lambda d: (d["delta"], d["field_id"]))
        reason = (
            f"{FOCUS_GROUP}-group field with the largest positive server-computed "
            f"field_production_kg delta in comparison {cmp['comparison_id']} (B0 {b0} -> P {p}): "
            f"+{best['delta']:.1f} {best['unit']} ({best['a']:.1f} -> {best['b']:.1f})"
        )
        return best["field_id"], reason, cmp["comparison_id"]
    reason = (
        f"comparison {cmp['comparison_id']} (B0 -> P) shows no positive field_production_kg delta "
        f"for any {FOCUS_GROUP}-group field; first {FOCUS_GROUP} field by ID"
    )
    return tail[0], reason, cmp["comparison_id"]


def _by_date(tl: dict, series_ids: set[str]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for s in tl["series"]:
        if s["series_id"] in series_ids:
            for d, v in zip(tl["dates"], s["values"], strict=True):
                if v is not None:
                    out[d] += v
    return out


def pick_decisive_date(c: httpx.Client, b0: str, p: str, field: str) -> tuple[str | None, str]:
    q = {"field_id": field, "resolution": "daily"}
    tp = call(c, "GET", f"/api/v2/runs/{p}/timeline", params=q)
    added = _by_date(tp, {"pond_release_m3", "pump_m3"})
    added = {d: v for d, v in added.items() if v > 0}
    if added:
        d = max(sorted(added), key=lambda k: added[k])
        return d, (
            f"date of the largest pond release + groundwater pumping for {field} in the P run's "
            f"daily ledger timeline ({added[d]:.1f} m3, state {tp['state_id']})"
        )
    tb = call(c, "GET", f"/api/v2/runs/{b0}/timeline", params=q)
    ap = _by_date(tp, {"field_application_m3"})
    ab = _by_date(tb, {"field_application_m3"})
    diff = {d: ap.get(d, 0.0) - ab.get(d, 0.0) for d in set(ap) | set(ab)}
    diff = {d: v for d, v in diff.items() if v > 0}
    if diff:
        d = max(sorted(diff), key=lambda k: diff[k])
        return d, (
            f"no pond release or pumping for {field} in P; date of the largest P - B0 gross field "
            f"application difference in the daily ledger timelines (+{diff[d]:.1f} m3)"
        )
    return None, (
        f"neither pond release/pumping nor a positive P - B0 field application difference for "
        f"{field} in the server timelines; no decisive date is claimed"
    )


def plan_turn(
    c: httpx.Client, doc: dict, goal: str, timeout: float = PLAN_TURN_TIMEOUT_S
) -> dict[str, str]:
    """Run one plan-mode copilot turn on the manifest's base revision / P run and wait for it.

    Only a ``completed`` turn is recorded: a partial (budget_exhausted), failed or provider-unavailable
    turn exits non-zero with its real status and error, so the tour never replays an unfinished brief."""
    ctx = {
        "pilot_id": doc["pilot_id"],
        "pilot_version": doc["pilot_version"],
        "season_id": doc["season_id"],
        "scenario_revision_id": doc["base"]["revision_id"],
        "selected_run_id": doc["base"]["runs"]["P"],
        "view": "plan-season",
        "language": "en",
    }
    sess = call(
        c, "POST", "/api/v2/copilot/sessions", ok=(201,), json={"context": ctx, "role": "planner"}
    )
    acc = call(
        c,
        "POST",
        f"/api/v2/copilot/sessions/{sess['session_id']}/messages",
        ok=(202,),
        json={"message": goal, "context": ctx, "mode": "plan"},
    )
    tid = acc["turn_id"]
    print(f"plan turn {tid}: {goal!r}")
    t0 = time.monotonic()
    t: dict = {}
    while time.monotonic() - t0 < timeout:
        t = call(c, "GET", f"/api/v2/copilot/turns/{tid}")
        if t["status"] != "running":
            break
        time.sleep(2.0)
    else:
        raise SeedError(f"plan turn {tid} did not finish in {timeout:.0f} s")
    if t["status"] != "completed":
        raise SeedError(f"plan turn {tid} ended {t['status']}: {t.get('error')}")
    print(f"  completed in {t.get('latency_ms')} ms, {t.get('rounds')} rounds")
    return {"plan_turn_id": tid, "plan_goal": goal, "plan_computed_at": t["finished_at"]}


def add_plan(c: httpx.Client, out: Path, goal: str) -> dict:
    """--plan-only: add a plan turn to the existing manifest (nothing is re-solved) and rewrite it."""
    if not out.is_file():
        raise SeedError(f"no manifest at {out}; run the full seed first")
    doc = json.loads(out.read_text())
    DemoManifest.model_validate(doc)
    doc.update(plan_turn(c, doc, goal))
    DemoManifest.model_validate(doc)
    write_atomic(out, doc)
    return doc


def write_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".session-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(doc, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "demo" / "session.json")
    ap.add_argument("--time-limit-s", type=float, default=30.0, help="per-solve CP-SAT limit")
    ap.add_argument(
        "--plan-goal",
        help='also run one "Plan my season" copilot turn with this goal and store it in the manifest',
    )
    ap.add_argument(
        "--plan-only",
        action="store_true",
        help="with --plan-goal: add the plan turn to the existing manifest without re-solving",
    )
    args = ap.parse_args()
    if args.plan_only:
        if not args.plan_goal:
            ap.error("--plan-only needs --plan-goal")
        with httpx.Client(base_url=args.base_url, timeout=120) as c:
            doc = add_plan(c, args.out, args.plan_goal)
        print(f"plan turn {doc['plan_turn_id']} added to {args.out}")
        return 0

    timings: dict[str, float] = {}
    t_all = time.monotonic()

    def timed(key: str, fn, *a):
        t0 = time.monotonic()
        out = fn(*a)
        timings[key] = round(time.monotonic() - t0, 2)
        return out

    with httpx.Client(base_url=args.base_url, timeout=120) as c:
        health = call(c, "GET", "/api/v2/health")
        if health["status"] != "ok" or health["dispatcher"] != "running":
            raise SeedError(f"API not ready: {health}")
        print(f"API {args.base_url} contract {health['contract_version']}")

        created = call(c, "POST", "/api/v2/scenarios", ok=(201,), json={"request": REQ})
        sid = created["scenario_id"]
        rid = created["revision"]["revision"]["scenario_revision_id"]
        if not created["revision"]["readiness"]["ready"]:
            raise SeedError(f"revision {rid} not ready: {created['revision']['readiness']}")
        print(f"scenario {sid} revision {rid}")

        views: dict[str, dict] = {}
        base_runs: dict[str, str] = {}
        for kind in ("B0", "B1", "P", "R"):
            v = timed(f"base_{kind}", solve, c, rid, kind, args.time_limit_s)
            views[v["run"]["run_id"]] = v
            base_runs[kind] = v["run"]["run_id"]
        base_p = views[base_runs["P"]]
        if not base_p["run"]["selected_intervention_instance_ids"]:
            raise SeedError(
                f"base P {base_runs['P']} buys no intervention at {BASE_CAPITAL_PKR} PKR; "
                "the capital-planning story needs a portfolio"
            )

        print("budget change:")
        tried: list[int] = []
        child = None
        reason = ""
        for budget in CHILD_BUDGETS_PKR:
            tried.append(budget)
            rev = call(
                c,
                "POST",
                f"/api/v2/scenarios/{sid}/revisions",
                ok=(201,),
                json={"parent_revision_id": rid, "changes": {"capital_budget_pkr": budget}},
            )
            crid = rev["revision"]["scenario_revision_id"]
            pv = timed(f"child_{budget}_P", solve, c, crid, "P", args.time_limit_s)
            if portfolio(pv) != portfolio(base_p):
                child = (budget, crid, pv)
                reason = portfolio_change(budget, base_p, pv)
                if len(tried) > 1:
                    reason += f"; earlier budgets {tried[:-1]} left the portfolio unchanged"
                break
            print(f"  {budget} PKR leaves the P portfolio unchanged; trying the next budget")
        if child is None:
            raise SeedError(f"no budget in {list(CHILD_BUDGETS_PKR)} changed the P portfolio")
        budget, crid, pv = child
        views[pv["run"]["run_id"]] = pv
        child_runs = {"P": pv["run"]["run_id"]}
        for kind in ("B0", "B1"):
            v = timed(f"child_{kind}", solve, c, crid, kind, args.time_limit_s)
            views[v["run"]["run_id"]] = v
            child_runs[kind] = v["run"]["run_id"]

        print("analyses:")
        fr = timed(
            "frontier",
            analyse,
            c,
            "frontier",
            {"base_revision_id": rid, "time_limit_per_point_s": 15, "settings": FRONTIER_SETTINGS},
        )
        st = timed(
            "stress",
            analyse,
            c,
            "stress",
            {"run_id": base_runs["R"], "reference_run_id": base_runs["P"]},
        )

        pmap = call(
            c, "GET", f"/api/v2/pilots/{REQ['pilot_id']}/versions/{REQ['pilot_version']}/map"
        )
        focus, focus_reason, cmp_id = pick_focus(
            c, base_runs["B0"], base_runs["P"], pmap["field_groups"]
        )
        ddate, ddate_reason = pick_decisive_date(c, base_runs["B0"], base_runs["P"], focus)

        doc = {
            "manifest_version": 1,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "api": {
                "base_url": args.base_url,
                "contract_version": health["contract_version"],
                "versions": health["versions"],
            },
            "pilot_id": REQ["pilot_id"],
            "pilot_version": REQ["pilot_version"],
            "season_id": REQ["season_id"],
            "scenario_request": REQ,
            "scenario_id": sid,
            "base": {"revision_id": rid, "runs": base_runs},
            "budget_change": {
                "revision_id": crid,
                "parent_revision_id": rid,
                "changes": {"capital_budget_pkr": budget},
                "runs": {k: child_runs[k] for k in ("B0", "B1", "P")},
                "selection_reason": reason,
                "tried_capital_budgets_pkr": tried,
            },
            "analyses": {"frontier": fr["analysis_id"], "stress": st["analysis_id"]},
            "comparison_id": cmp_id,
            "focus_field_id": focus,
            "focus_field_reason": focus_reason,
            "decisive_date": ddate,
            "decisive_date_reason": ddate_reason,
            "run_details": {k: detail(v) for k, v in views.items()},
            "timings_s": timings,
            "notes": NOTES,
        }
        if args.plan_goal:
            doc.update(timed("plan_turn", plan_turn, c, doc, args.plan_goal))
    timings["total"] = round(time.monotonic() - t_all, 2)
    DemoManifest.model_validate(doc)  # the route must be able to serve what we write
    write_atomic(args.out, doc)

    print()
    print(f"scenario {sid}")
    print(f"  base revision {rid}: " + ", ".join(f"{k}={v}" for k, v in base_runs.items()))
    print(
        f"  budget change {crid} ({budget} PKR): "
        + ", ".join(f"{k}={child_runs[k]}" for k in ("B0", "B1", "P"))
    )
    print(f"  frontier {fr['analysis_id']}  stress {st['analysis_id']}")
    print(f"  focus field {focus}: {focus_reason}")
    print(f"  decisive date {ddate}: {ddate_reason}")
    print(f"  total {timings['total']} s")
    try:
        shown = args.out.resolve().relative_to(ROOT)
    except ValueError:
        shown = args.out
    print(f"wrote {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
