"""F19 live smoke: a handful of real hosted-model turns through the copilot routes on real pilot data.

Builds an in-process app over read-only links to the published data (pilots, libraries,
models, experiments) and a temporary database, solves the real B0/B1/P/R ladder of
pilot-a wheat 2027-28, runs a fixed-plan stress test and a frontier, then asks a few lay
questions through POST /copilot/sessions/{id}/messages exactly like the UI. Saves a
sanitized transcript (no secrets) with timings to evidence/copilot/smoke-<UTC>.json.

This is a smoke run, not the T11.8 30x3 evaluation, and it does not certify AT17.

    docker run --rm --user 1000:1000 --env-file <repo>/.env -v <worktree>:/app \
        -v <repo>/data/pilots:/realdata/pilots:ro ... aabflow-dev:local python scripts/copilot_smoke.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

# (case id, what it covers, message, session key)
CASES = [
    (
        "S1",
        "lay best-plan question with a chart",
        "What's the best plan for our canal this season? Keep it simple.",
        "main",
    ),
    (
        "S2",
        "what-if budget change that solves a new run",
        "What if we only had 10 lakh rupees to spend instead?",
        "main",
    ),
    (
        "S3",
        "stress / robustness with heatmap",
        "How robust is our plan if we get a dry year or the canal water is cut?",
        "main",
    ),
    (
        "S4",
        "fairness / tail fields with table",
        "Which farmers lose out? Are the tail-end fields treated fairly?",
        "main",
    ),
    (
        "S5",
        "Urdu question (what-if canal closure)",
        "اگر نہر دو ہفتے بند رہے تو ہماری فصل پر کیا اثر ہوگا؟",
        "urdu",
    ),
    (
        "S6",
        "failure case: tool error on a run that does not exist",
        "Compare our plan with run run_0000deadbeef please.",
        "fail",
    ),
    ("S7", "where the water goes (sankey)", "Where does all the canal water actually go?", "main"),
]

_SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{12,}")


def _link_data(tmp: Path, src: Path) -> Path:
    data = tmp / "data"
    data.mkdir()
    for d in ("pilots", "libraries", "models", "experiments"):
        (data / d).symlink_to(src / d, target_is_directory=True)
    return data


def _wait(c, job_id: str, timeout: float = 900) -> dict[str, Any]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/v2/jobs/{job_id}").json()
        if j["state"] in ("succeeded", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.3)
    raise RuntimeError(f"job {job_id} timed out")


def prepare(c) -> dict[str, Any]:
    t0 = time.time()
    r = c.post("/api/v2/scenarios", json={"label": "Pilot A wheat 2027-28 plan", "request": REQ})
    r.raise_for_status()
    rid = r.json()["revision"]["revision"]["scenario_revision_id"]
    runs = {}
    for kind in ("B0", "B1", "P", "R"):
        j = c.post(
            f"/api/v2/scenario-revisions/{rid}/solve", json={"plan_kind": kind, "time_limit_s": 30}
        ).json()
        j = _wait(c, j["job_id"])
        if j["state"] != "succeeded":
            raise RuntimeError(f"{kind} solve {j['state']}")
        runs[kind] = j["result_ref"]
    a = c.post("/api/v2/analyses/stress", json={"run_id": runs["P"]}).json()
    stress = _wait(c, a["job_id"])["state"]
    f = c.post(
        "/api/v2/analyses/frontier",
        json={
            "base_revision_id": rid,
            "time_limit_per_point_s": 15,
            "settings": [{"capital_budget_pkr": v} for v in (0, 500000, 1500000, 3000000, 8000000)]
            + [
                {
                    "capital_budget_pkr": 3000000,
                    "minimum_service_ratio": 0.6,
                    "service_group": "tail",
                }
            ],
        },
    ).json()
    frontier = _wait(c, f["job_id"])["state"]
    return {
        "revision_id": rid,
        "runs": runs,
        "stress_analysis_id": a["analysis_id"],
        "stress_state": stress,
        "frontier_analysis_id": f["analysis_id"],
        "frontier_state": frontier,
        "prepare_s": round(time.time() - t0, 1),
    }


def ui_context(env: dict[str, Any], language: str = "en") -> dict[str, Any]:
    return {
        "pilot_id": "pilot-a",
        "pilot_version": "reviewed-v1",
        "season_id": SEASON,
        "scenario_revision_id": env["revision_id"],
        "selected_run_id": env["runs"]["P"],
        "selected_field_id": None,
        "view": "workspace",
        "language": language,
    }


def ask(
    c, session_id: str, message: str, ctx: dict[str, Any], timeout: float = 200
) -> dict[str, Any]:
    t0 = time.time()
    r = c.post(
        f"/api/v2/copilot/sessions/{session_id}/messages", json={"message": message, "context": ctx}
    )
    if r.status_code != 202:
        return {"status": "rejected", "http": r.status_code, "body": r.json(), "wall_s": 0}
    tid = r.json()["turn_id"]
    while time.time() - t0 < timeout:
        t = c.get(f"/api/v2/copilot/turns/{tid}", params={"include_tools": True}).json()
        if t["status"] != "running":
            t["wall_s"] = round(time.time() - t0, 1)
            return t
        time.sleep(0.5)
    raise RuntimeError(f"turn {tid} did not finish")


def summarize_turn(case: tuple, t: dict[str, Any]) -> dict[str, Any]:
    cid, covers, message, _ = case
    answer = t.get("answer") or {}
    blocks = answer.get("blocks") or []
    calls = []
    for call in t.get("tool_calls") or []:
        res = call.get("result") or {}
        calls.append(
            {
                "call_id": call["call_id"],
                "round": call["round"],
                "tool": call["tool"],
                "arguments": call["arguments"],
                "status": call["status"],
                "error": (res.get("error") if isinstance(res, dict) else None),
                "datasets": [
                    {k: d.get(k) for k in ("dataset_id", "kind", "title", "rows", "charts")}
                    for d in (
                        res.get("datasets") or (res.get("analysis") or {}).get("datasets") or []
                    )
                ]
                if isinstance(res, dict)
                else [],
            }
        )
    events = t.get("events") or []
    return {
        "case": cid,
        "covers": covers,
        "message": message,
        "turn_id": t.get("turn_id"),
        "status": t.get("status"),
        "language": t.get("language"),
        "wall_s": t.get("wall_s"),
        "latency_ms": t.get("latency_ms"),
        "rounds": t.get("rounds"),
        "timings": t.get("timings"),
        "model": t.get("model"),
        "prompt_version": t.get("prompt_version"),
        "tool_schema_version": t.get("tool_schema_version"),
        "provider_request_ids": t.get("request_ids"),
        "tool_calls": calls,
        "created_refs": t.get("created_refs"),
        "error": t.get("error"),
        "answer_validated": answer.get("validated"),
        "answer_issues": answer.get("issues"),
        "block_types": [b["type"] for b in blocks],
        "visuals": [
            {
                "chart": b["chart"],
                "title": b["title"],
                "dataset_kind": b["dataset_kind"],
                "rows": len(b["rows"]),
                "source": b["source"],
            }
            for b in blocks
            if b["type"] == "visual"
        ],
        "answer": answer,
        "event_types": [e["type"] for e in events],
    }


def sanitize(obj: Any) -> Any:
    key = os.environ.get("OPENAI_API_KEY") or ""
    if isinstance(obj, str):
        s = _SECRET.sub("[redacted]", obj)
        return s.replace(key, "[redacted]") if len(key) >= 8 else s
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("AABFLOW_SMOKE_DATA", "/realdata"))
    ap.add_argument("--cases", default="")
    ap.add_argument("--out", default=str(ROOT / "evidence" / "copilot"))
    args = ap.parse_args()
    os.environ.setdefault("AABFLOW_OPENAI_MODEL", "gpt-6-luna")
    from fastapi.testclient import TestClient

    from aabflow.config import Settings
    from aabflow.copilot.provider import configured_model, key_configured
    from aabflow.main import create_app

    selected = [c for c in CASES if not args.cases or c[0] in args.cases.split(",")]
    tmp = Path(tempfile.mkdtemp(prefix="copilot-smoke-"))
    data = _link_data(tmp, Path(args.data))
    s = Settings(
        data_dir=data,
        db_path=tmp / "app.sqlite",
        web_dist=tmp / "nowd",
        workers=2,
        solver_workers=2,
    )
    started = datetime.now(UTC)
    record: dict[str, Any] = {
        "kind": "copilot-live-smoke",
        "note": "Live hosted-model smoke on real pilot data; not the T11.8 30x3 evaluation and not AT17.",
        "started_at": started.isoformat(),
        "model": configured_model(),
        "key_configured": key_configured(),
        "pilot": {"pilot_id": "pilot-a", "pilot_version": "reviewed-v1", "season_id": SEASON},
        "turns": [],
    }
    with TestClient(create_app(s)) as c:
        record["copilot_status"] = c.get("/api/v2/copilot/status").json()
        env = prepare(c)
        record["prepared"] = env
        print(json.dumps(env), flush=True)
        sessions: dict[str, str] = {}
        for case in selected:
            key = case[3]
            lang = "ur" if key == "urdu" else "en"
            if key not in sessions:
                r = c.post("/api/v2/copilot/sessions", json={"context": ui_context(env, lang)})
                r.raise_for_status()
                sessions[key] = r.json()["session_id"]
            t = ask(c, sessions[key], case[2], ui_context(env, lang))
            row = summarize_turn(case, t)
            record["turns"].append(row)
            print(
                f"{case[0]} {row['status']:<20} {row['wall_s']:>6}s rounds={row['rounds']} "
                f"tools={[x['tool'] for x in row['tool_calls']]} visuals={[v['chart'] for v in row['visuals']]} "
                f"validated={row['answer_validated']}",
                flush=True,
            )
        record["sessions"] = sessions
    record["finished_at"] = datetime.now(UTC).isoformat()
    walls = [t["wall_s"] for t in record["turns"] if t.get("wall_s") is not None]
    record["summary"] = {
        "turns": len(record["turns"]),
        "statuses": {t["case"]: t["status"] for t in record["turns"]},
        "wall_s": {"min": min(walls, default=None), "max": max(walls, default=None)},
        "provider_call_ms": [
            p["latency_ms"]
            for t in record["turns"]
            for p in ((t.get("timings") or {}).get("provider_calls") or [])
        ],
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"smoke-{started:%Y%m%dT%H%M%SZ}.json"
    text = json.dumps(sanitize(record), indent=1, ensure_ascii=False, default=str)
    assert not _SECRET.search(text), "secret-like string in transcript"
    path.write_text(text)
    print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
