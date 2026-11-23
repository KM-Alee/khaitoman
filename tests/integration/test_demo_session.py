"""Guided-demo manifest: ``GET /api/v2/demo/session`` and the seed script's server-derived choices.

Every manifest, database row, run bundle and HTTP response below is a labelled TEST FIXTURE built
in a temporary directory; none of these IDs or numbers are real results.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from aabflow.api.demo import DemoManifest, manifest_path
from aabflow.main import create_app
from tests.fixtures.api_app import settings_for

_SPEC = importlib.util.spec_from_file_location(
    "seed_demo_session", Path(__file__).resolve().parents[2] / "scripts/seed_demo_session.py"
)
assert _SPEC and _SPEC.loader
seed = importlib.util.module_from_spec(_SPEC)
sys.modules["seed_demo_session"] = seed
_SPEC.loader.exec_module(seed)

NOW = "2026-10-10T08:00:00.000000Z"


def fixture_manifest() -> dict:
    """TEST FIXTURE manifest; IDs are invented and exist in no real database."""
    return {
        "manifest_version": 1,
        "created_at": "2026-10-10T08:00:00Z",
        "api": {
            "base_url": "http://fixture",
            "contract_version": "2.0.0",
            "versions": {"ortools": "fixture"},
        },
        "pilot_id": "pilot-a",
        "pilot_version": "reviewed-v1",
        "season_id": "wheat-rabi-2027-28",
        "scenario_request": {"pilot_id": "pilot-a", "capital_budget_pkr": 3000000},
        "scenario_id": "scn_fixture",
        "base": {
            "revision_id": "rev_fixture_base",
            "runs": {"B0": "run_fx_b0", "B1": "run_fx_b1", "P": "run_fx_p", "R": "run_fx_r"},
        },
        "budget_change": {
            "revision_id": "rev_fixture_child",
            "parent_revision_id": "rev_fixture_base",
            "changes": {"capital_budget_pkr": 500000},
            "runs": {"B0": "run_fx_c_b0", "B1": "run_fx_c_b1", "P": "run_fx_c_p"},
            "selection_reason": "fixture",
            "tried_capital_budgets_pkr": [500000],
        },
        "analyses": {"frontier": "ana_fx_frontier", "stress": "ana_fx_stress"},
        "comparison_id": "cmp_fixture",
        "focus_field_id": "pilot-a:field-001",
        "focus_field_reason": "fixture",
        "decisive_date": "2027-01-15",
        "decisive_date_reason": "fixture",
        "run_details": {
            "run_fx_p": {
                "plan_kind": "P",
                "outcome": "plan",
                "solver_status": "OPTIMAL",
                "created_at": "2026-10-10T08:00:00Z",
                "production_kg": 1.0,
            }
        },
        "timings_s": {"total": 1.0},
    }


ALL_IDS = [
    "scn_fixture",
    "rev_fixture_base",
    "rev_fixture_child",
    "run_fx_b0",
    "run_fx_b1",
    "run_fx_p",
    "run_fx_r",
    "run_fx_c_b0",
    "run_fx_c_b1",
    "run_fx_c_p",
    "ana_fx_frontier",
    "ana_fx_stress",
]


@pytest.fixture
def app_dir(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        yield client, tmp_path


def write_manifest(tmp: Path, text: str) -> None:
    p = manifest_path(tmp)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def assert_not_found(r: httpx.Response, phrase: str) -> None:
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "NOT_FOUND" and body["fields"] == {}
    assert phrase in body["detail"] and "make demo-seed" in body["detail"]


def test_absent_manifest_is_json_404(app_dir):
    client, _ = app_dir
    assert_not_found(client.get("/api/v2/demo/session"), "No demo session manifest")


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        json.dumps({**fixture_manifest(), "manifest_version": 2}),
        json.dumps({**fixture_manifest(), "unexpected": True}),
        json.dumps({k: v for k, v in fixture_manifest().items() if k != "base"}),
    ],
    ids=["not-json", "not-object", "wrong-version", "extra-key", "missing-base"],
)
def test_malformed_manifest_is_json_404(app_dir, text):
    client, tmp = app_dir
    write_manifest(tmp, text)
    assert_not_found(client.get("/api/v2/demo/session"), "unreadable or invalid")


def test_manifest_with_no_records_reports_every_id_missing(app_dir):
    client, tmp = app_dir
    write_manifest(tmp, json.dumps(fixture_manifest()))
    r = client.get("/api/v2/demo/session")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["complete"] is False
    assert sorted(body["missing_ids"]) == sorted(ALL_IDS)
    assert set(body["available"]) == set(ALL_IDS) and not any(body["available"].values())
    assert body["base"]["runs"]["P"] == "run_fx_p"
    assert body["decisive_date"] == "2027-01-15"
    assert body["run_details"]["run_fx_p"]["created_at"] == "2026-10-10T08:00:00Z"


def insert_fixture_records(tmp: Path, ids: list[str], *, bundle: bool = True) -> None:
    """TEST FIXTURE rows (not real runs): enough columns for the existence check."""
    conn = sqlite3.connect(tmp / "app.sqlite")
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for i in ids:
            if i.startswith("scn_"):
                conn.execute(
                    "INSERT INTO scenarios (scenario_id, pilot_id, created_at) VALUES (?,?,?)",
                    (i, "pilot-a", NOW),
                )
            elif i.startswith("rev_"):
                conn.execute(
                    "INSERT INTO scenario_revisions (scenario_revision_id, scenario_id, "
                    "parent_revision_id, request, semantic_hash, dependencies, readiness, "
                    "created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        i,
                        "scn_fixture",
                        None,
                        json.dumps(fixture_request()),
                        "0" * 64,
                        "{}",
                        "{}",
                        NOW,
                    ),
                )
            elif i.startswith("run_"):
                run_dir = tmp / "runs" / i
                run_dir.mkdir(parents=True, exist_ok=True)
                if bundle:
                    (run_dir / "manifest.json").write_text('{"files": []}')
                conn.execute(
                    "INSERT INTO runs (run_id, scenario_revision_id, plan_kind, outcome, "
                    "solver_status, scenario_hash, candidate_library_hash, run_dir, "
                    "manifest_sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        i,
                        "rev_fixture_base",
                        "P",
                        "plan",
                        "OPTIMAL",
                        "x",
                        "x",
                        str(run_dir),
                        "x",
                        NOW,
                    ),
                )
            elif i.startswith("ana_"):
                conn.execute(
                    "INSERT INTO analyses (analysis_id, kind, request, created_at, updated_at) "
                    "VALUES (?,?,?,?,?)",
                    (i, "frontier", "{}", NOW, NOW),
                )
        conn.commit()
    finally:
        conn.close()


def fixture_request() -> dict:
    return {
        "pilot_id": "pilot-a",
        "pilot_version": "reviewed-v1",
        "season_id": "wheat-rabi-2027-28",
        "planning_mode": "capital_planning",
        "decision_at": "2026-10-10T08:00:00+05:00",
        "weather_scenario_ids": ["typical"],
        "supply_profile_id": "nominal-roster-v1",
        "capital_budget_pkr": 3000000,
        "operating_budget_pkr": 400000,
    }


def test_partial_database_lists_only_missing_ids_and_writes_nothing(app_dir):
    client, tmp = app_dir
    write_manifest(tmp, json.dumps(fixture_manifest()))
    present = ["scn_fixture", "rev_fixture_base", "run_fx_p", "run_fx_b0", "ana_fx_frontier"]
    insert_fixture_records(tmp, present)
    insert_fixture_records(tmp, ["run_fx_r"], bundle=False)  # row whose bundle is gone
    before = _counts(tmp)
    body = client.get("/api/v2/demo/session").json()
    assert body["complete"] is False
    assert all(body["available"][i] for i in present)
    assert body["available"]["run_fx_r"] is False
    assert sorted(body["missing_ids"]) == sorted(set(ALL_IDS) - set(present))
    assert _counts(tmp) == before  # read-only: no jobs, rows or comparisons created


def test_complete_when_every_record_exists(app_dir):
    client, tmp = app_dir
    write_manifest(tmp, json.dumps(fixture_manifest()))
    insert_fixture_records(tmp, ALL_IDS)
    body = client.get("/api/v2/demo/session").json()
    assert body["complete"] is True and body["missing_ids"] == []


@pytest.mark.parametrize(
    "mode,status,available",
    [
        (None, None, False),
        ("chat", "completed", False),
        ("plan", "failed", False),
        ("plan", "running", False),
        ("plan", "completed", True),
    ],
)
def test_saved_plan_requires_a_completed_plan_turn(app_dir, mode, status, available):
    client, tmp = app_dir
    write_manifest(tmp, json.dumps({**fixture_manifest(), "plan_turn_id": "turn_fx"}))
    insert_fixture_records(tmp, ALL_IDS)
    if mode is not None:
        with sqlite3.connect(tmp / "app.sqlite") as conn:
            conn.execute(
                "INSERT INTO copilot_sessions (session_id, created_at, role, ui_context) "
                "VALUES ('cps_fx', ?, 'planner', '{}')",
                (NOW,),
            )
            conn.execute(
                "INSERT INTO copilot_turns (turn_id, session_id, seq, created_at, status, "
                "user_message, context, mode) VALUES ('turn_fx', 'cps_fx', 1, ?, ?, 'goal', '{}', ?)",
                (NOW, status, mode),
            )
    body = client.get("/api/v2/demo/session").json()
    assert body["available"]["turn_fx"] is available
    assert body["complete"] is available
    assert body["missing_ids"] == ([] if available else ["turn_fx"])


def _counts(tmp: Path) -> dict[str, int]:
    conn = sqlite3.connect(tmp / "app.sqlite")
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("jobs", "runs", "analyses", "comparisons", "scenario_revisions")
        }
    finally:
        conn.close()


def test_demo_route_is_in_openapi(app_dir):
    client, _ = app_dir
    spec = client.get("/api/v2/openapi.json").json()
    op = spec["paths"]["/api/v2/demo/session"]["get"]
    ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/DemoSession")
    props = spec["components"]["schemas"]["DemoSession"]["properties"]
    assert {"missing_ids", "complete", "available", "focus_field_id", "decisive_date"} <= set(props)


# ------------------------------------------------------------------ seed script (mock HTTP)


def mock_client(routes: dict[tuple[str, str], tuple[int, object]]) -> httpx.Client:
    """TEST FIXTURE transport: fixed responses keyed by (method, path)."""

    def handler(req: httpx.Request) -> httpx.Response:
        status, body = routes[(req.method, req.url.path)]
        return httpx.Response(status, json=body)

    return httpx.Client(base_url="http://fixture", transport=httpx.MockTransport(handler))


def test_seed_focus_field_uses_largest_positive_tail_delta():
    deltas = [
        {"metric_id": "field_production_kg", "field_id": f, "delta": d, "a": 10.0, "b": 10.0 + d}
        | {"unit": "kg"}
        for f, d in (("f-head", 900.0), ("f-tail-1", 50.0), ("f-tail-2", 120.0), ("f-tail-3", -5))
    ]
    c = mock_client(
        {("POST", "/api/v2/comparisons"): (201, {"comparison_id": "cmp_fx", "deltas": deltas})}
    )
    groups = {"f-head": "head", "f-tail-1": "tail", "f-tail-2": "tail", "f-tail-3": "tail"}
    fid, reason, cid = seed.pick_focus(c, "run_b0", "run_p", groups)
    assert (fid, cid) == ("f-tail-2", "cmp_fx")
    assert "+120.0 kg" in reason


def test_seed_focus_field_falls_back_with_reason():
    c = mock_client({("POST", "/api/v2/comparisons"): (201, {"comparison_id": "c", "deltas": []})})
    fid, reason, _ = seed.pick_focus(c, "a", "b", {"f2": "tail", "f1": "tail", "f0": "head"})
    assert fid == "f1" and "no positive" in reason


def _timeline(series: dict[str, list[float | None]], dates: list[str]) -> dict:
    return {
        "dates": dates,
        "state_id": "typical",
        "series": [{"series_id": k, "values": v} for k, v in series.items()],
    }


def test_seed_decisive_date_from_pond_release_and_pumping():
    dates = ["2027-01-01", "2027-01-02", "2027-01-03"]
    tl = _timeline({"pond_release_m3": [0, 30.0, None], "pump_m3": [5.0, 0, 40.0]}, dates)
    c = mock_client({("GET", "/api/v2/runs/run_p/timeline"): (200, tl)})
    d, reason = seed.pick_decisive_date(c, "run_b0", "run_p", "f1")
    assert d == "2027-01-03" and "pond release + groundwater pumping" in reason


def test_seed_decisive_date_is_null_without_server_basis():
    dates = ["2027-01-01"]
    flat = _timeline({"field_application_m3": [10.0]}, dates)
    c = mock_client(
        {
            ("GET", "/api/v2/runs/run_p/timeline"): (200, flat),
            ("GET", "/api/v2/runs/run_b0/timeline"): (200, flat),
        }
    )
    d, reason = seed.pick_decisive_date(c, "run_b0", "run_p", "f1")
    assert d is None and "no decisive date" in reason


def test_seed_fails_loudly_on_failed_job_or_non_plan_outcome():
    job = {"job_id": "job_fx", "state": "failed", "error": {"code": "MODEL_INVALID"}}
    c = mock_client(
        {
            ("POST", "/api/v2/scenario-revisions/rev/solve"): (202, {"job_id": "job_fx"}),
            ("GET", "/api/v2/jobs/job_fx"): (200, job),
        }
    )
    with pytest.raises(SystemExit, match="P solve on rev: job job_fx failed"):
        seed.solve(c, "rev", "P", 5)
    ok = {**job, "state": "succeeded", "result_ref": "run_fx"}
    view = {
        "run": {"run_id": "run_fx", "outcome": "no_plan", "solver_status": "INFEASIBLE"},
        "metrics": [],
    }
    c = mock_client(
        {
            ("POST", "/api/v2/scenario-revisions/rev/solve"): (202, {"job_id": "job_fx"}),
            ("GET", "/api/v2/jobs/job_fx"): (200, ok),
            ("GET", "/api/v2/runs/run_fx"): (200, view),
        }
    )
    with pytest.raises(SystemExit, match="outcome no_plan"):
        seed.solve(c, "rev", "P", 5)


def test_seed_resubmits_only_server_cancelled_jobs(monkeypatch):
    """A restart-cancelled job is resubmitted (and noted); repeated cancels still fail loudly."""
    monkeypatch.setattr(seed, "NOTES", [])
    states = iter(["cancelled", "succeeded"])
    posted: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            posted.append(req.url.path)
            return httpx.Response(202, json={"job_id": f"job_{len(posted)}"})
        if req.url.path.startswith("/api/v2/jobs/"):
            jid = req.url.path.rsplit("/", 1)[1]
            st = next(states)
            return httpx.Response(
                200, json={"job_id": jid, "state": st, "stage": "solving", "result_ref": "run_fx"}
            )
        return httpx.Response(
            200,
            json={
                "run": {"run_id": "run_fx", "outcome": "plan", "solver_status": "OPTIMAL"},
                "metrics": [],
            },
        )

    c = httpx.Client(base_url="http://fixture", transport=httpx.MockTransport(handler))
    assert seed.solve(c, "rev", "B0", 5)["run"]["run_id"] == "run_fx"
    assert len(posted) == 2 and len(seed.NOTES) == 1 and "job_1 cancelled" in seed.NOTES[0]

    states = iter(["interrupted"] * seed.MAX_ATTEMPTS)
    with pytest.raises(SystemExit, match="interrupted"):
        seed.solve(c, "rev", "B0", 5)


def test_seed_portfolio_change_reports_server_difference():
    def view(ids, cap, prod):
        return {
            "run": {"selected_intervention_instance_ids": ids},
            "metrics": [
                {"metric_id": "capital_commitment_pkr", "field_id": None, "value": cap},
                {"metric_id": "production_kg", "field_id": None, "value": prod},
            ],
        }

    text = seed.portfolio_change(500000, view(["a", "b"], 900.0, 10.0), view(["a"], 100.0, 9.0))
    assert "drops ['b']" in text and "adds" not in text
    assert "900 -> 100 PKR" in text and "10 -> 9 kg" in text


def test_seed_rejected_request_and_atomic_write(tmp_path):
    c = mock_client({("GET", "/api/v2/health"): (503, {"code": "ASSET_UNAVAILABLE"})})
    with pytest.raises(SystemExit, match="503"):
        seed.call(c, "GET", "/api/v2/health")
    out = tmp_path / "demo" / "session.json"
    seed.write_atomic(out, fixture_manifest())
    assert DemoManifest.model_validate(json.loads(out.read_text())).scenario_id == "scn_fixture"
    assert [p.name for p in out.parent.iterdir()] == ["session.json"]


def _plan_routes(status: str) -> dict:
    """TEST FIXTURE copilot responses for one plan-mode turn."""
    return {
        ("POST", "/api/v2/copilot/sessions"): (201, {"session_id": "cps_fx"}),
        ("POST", "/api/v2/copilot/sessions/cps_fx/messages"): (202, {"turn_id": "turn_fx"}),
        ("GET", "/api/v2/copilot/turns/turn_fx"): (
            200,
            {
                "turn_id": "turn_fx",
                "status": status,
                "error": None if status == "completed" else {"code": "TURN_TIMEOUT"},
                "finished_at": "2026-10-10T08:03:00Z",
                "latency_ms": 1,
                "rounds": 3,
            },
        ),
    }


def test_seed_plan_only_adds_the_plan_turn_without_resolving(tmp_path, app_dir):
    out = tmp_path / "demo" / "session.json"
    seed.write_atomic(out, fixture_manifest())
    posted: list[dict] = []
    routes = _plan_routes("completed")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            posted.append({"path": req.url.path, **json.loads(req.content)})
        status, body = routes[(req.method, req.url.path)]
        return httpx.Response(status, json=body)

    c = httpx.Client(base_url="http://fixture", transport=httpx.MockTransport(handler))
    goal = "We have 10 lakh. Protect the tail."
    doc = seed.add_plan(c, out, goal)
    assert [p["path"] for p in posted] == [  # no solve, no analysis: only the copilot turn
        "/api/v2/copilot/sessions",
        "/api/v2/copilot/sessions/cps_fx/messages",
    ]
    msg = posted[1]
    assert msg["mode"] == "plan" and msg["message"] == goal
    assert msg["context"]["scenario_revision_id"] == "rev_fixture_base"
    assert msg["context"]["selected_run_id"] == "run_fx_p"
    saved = json.loads(out.read_text())
    assert saved == doc and saved["scenario_id"] == "scn_fixture"
    assert (saved["plan_turn_id"], saved["plan_goal"], saved["plan_computed_at"]) == (
        "turn_fx",
        goal,
        "2026-10-10T08:03:00Z",
    )
    # GET /demo/session exposes the plan fields
    client, tmp = app_dir
    write_manifest(tmp, out.read_text())
    body = client.get("/api/v2/demo/session").json()
    assert body["plan_turn_id"] == "turn_fx" and body["plan_goal"] == goal


def test_seed_plan_turn_must_complete(tmp_path):
    c = mock_client(_plan_routes("budget_exhausted"))
    with pytest.raises(SystemExit, match="ended budget_exhausted"):
        seed.plan_turn(c, fixture_manifest(), "goal")
    with pytest.raises(SystemExit, match="no manifest"):
        seed.add_plan(c, tmp_path / "missing.json", "goal")
